from flask import Flask, request, render_template, redirect

app = Flask(__name__)
app.config['DEBUG'] = True
from google.appengine.ext import ndb

import json
import pytz
import datetime
import random
import time
import logging

# Note: We don't need to call run() since our application is embedded within
# the App Engine WSGI application server.

@app.route('/')
def hello():
    # Redirect to a chart
    return redirect("/chart/zomgbox-C1EB/temp", code=302)


@app.route('/chart/<identifier>/<type_>')
def chart(identifier, type_):
    since = request.args.get('since', str(int(time.time())-24*60*60)) # Last 24 hrs
    return render_template('chart.template.html', id = identifier, type = type_, since=since)


class Measurement(ndb.Model):
    timestamp = ndb.DateTimeProperty(auto_now_add=True)
    identifier = ndb.StringProperty()
    type = ndb.StringProperty()
    value = ndb.StringProperty()

    @classmethod
    def last(cls,identifier,type_):
        return cls.query(cls.identifier == identifier, cls.type == type_).order(-cls.timestamp)

    @classmethod
    def since(cls,identifier,type_, since):
        return cls.query(cls.identifier == identifier, cls.type == type_, cls.timestamp > since).order(cls.timestamp)

    @classmethod
    def all(cls,identifier,type_):
        return cls.query(cls.identifier == identifier, cls.type == type_).order(cls.timestamp)


class MeasurementBlock(ndb.Model):
    first = ndb.DateTimeProperty()
    last = ndb.DateTimeProperty()
    identifier = ndb.StringProperty()
    type = ndb.StringProperty()
    count = ndb.IntegerProperty()
    values = ndb.TextProperty()

    @classmethod
    def since(cls,identifier,type_, count, since):
        return cls.query(cls.identifier == identifier, cls.type == type_, cls.count == count, cls.last > since).order(cls.first)



def do_publish(identifier, type_, value, ts = None):
    indexdata(identifier, type_)
    measurement = Measurement(identifier=identifier, type=type_, value=value)
    if ts is not None:
        measurement.timestamp = ts
    measurement.put()

    if random.random() < .1:
        indexdata(identifier, type_)


@app.route('/publish')
def publish():
    secret = request.args.get('secret')
    identifier = request.args.get('id')
    for key, value in request.args.iteritems():
        if key in ("id", "secret"):
            continue
        do_publish(identifier, key, value)
    return "Ok."


@app.route('/show')
def show():
    measurements = Measurement.query().order(-Measurement.timestamp).fetch(20)
    reply = []
    for measurement in measurements:
        reply.append(
            "%s,%s,%s,%s<BR>" % (measurement.identifier, measurement.timestamp, measurement.type, measurement.value))
    return "\n".join(reply)


def format_jsdate(dt,tz):
    ## Format a datetime into a js Date()
    ## Notice the -1 in the month.
    dt = dt.astimezone(tz)
    return "Date(%d,%d,%d,%d,%d,%d)" % (dt.year, dt.month-1, dt.day, dt.hour, dt.minute, dt.second)


BLOCK_SIZE = 15
BLOCK_DEPTH = 3


def indexblocks(identifier, type_, depth):

    blocks = MeasurementBlock.query(MeasurementBlock.identifier == identifier, MeasurementBlock.type == type_,
                                    MeasurementBlock.count == BLOCK_SIZE ** depth).order(MeasurementBlock.first).fetch(keys_only=True)
    i = 0
    for blocknr in range(len(blocks) // BLOCK_SIZE):
        blockdata = []
        first, last = datetime.datetime(2999,12,31), datetime.datetime(1000,1,1)
        for bnr in range(BLOCK_SIZE):
            block = blocks[i].get()
            i+=1
            first = min(first, block.first)
            last = max(last, block.last)
            blockdata.extend(json.loads(block.values))
            block.key.delete()

        metablock = MeasurementBlock(identifier=identifier, type=type_, count = BLOCK_SIZE ** (depth+1),
                                     first = first, last = last, values = json.dumps(blockdata))
        metablock.put()

    return "Ok."

@app.route('/indexdata/<identifier>/<type_>')
def indexdata(identifier, type_):

    #identifier = request.args.get('id')
    #type_ = request.args.get('type')

    # Start at block depth N-1, aggregate blocks.
    depth = BLOCK_DEPTH-1
    count = BLOCK_SIZE ** depth

    # aggregate
    # now aggregate the individual measurements
    measurements = Measurement.all(identifier,type_).order(Measurement.timestamp).fetch(keys_only=True)
    i = 0
    for blocknr in range(len(measurements) // BLOCK_SIZE):
        blockdata = []
        to_delete = []
        first, last = datetime.datetime(2999,12,31), datetime.datetime(1000,1,1)
        for mnr in range(BLOCK_SIZE):
            measurement = measurements[i].get()
            if not measurement:
                return "Odd stuff."
            i += 1
            ts = measurement.timestamp
            blockdata.append((int(time.mktime(ts.timetuple())),measurement.value))
            first = min(first, ts)
            last = max(last, ts)
            to_delete.append(measurement.key)

        # Full block, add it
        block = MeasurementBlock(identifier=identifier, type = type_,
                                 count = BLOCK_SIZE, first = first, last = last,
                                 values = json.dumps(blockdata))
        block.put()
        for key in to_delete:
            key.delete()

    indexblocks(identifier, type_, 1)
    indexblocks(identifier, type_, 2)

    return "Ok."





@app.route('/getdata')
def getdata():
    identifier = request.args.get('id')
    type_ = request.args.get('type')
    callback = request.args.get('callback')
    tz = request.args.get('tz','UTC')
    tz = pytz.timezone(tz)
    since = request.args.get('since', str(int(time.time())-24*60*60)) # Last 24 hrs
    since = datetime.datetime.fromtimestamp(int(since), pytz.timezone('UTC'))


    result = {}
    result['cols'] = [{'id': 'A', 'label': 'time', 'type': 'datetime'},
         {'id': 'B', 'label': '%s' % type_, 'type': 'number'}, ]
    rows = []

    blocks = MeasurementBlock.query(MeasurementBlock.identifier == identifier, MeasurementBlock.type == type_,
                                    MeasurementBlock.last > since).order(MeasurementBlock.last).fetch()
    for block in blocks:
        logging.info('Reading from block %r' % block.key)
        for ts, value in json.loads(block.values):
            ts = datetime.datetime.utcfromtimestamp(ts).replace(tzinfo=pytz.timezone('UTC'))
            if ts > since:
                rows.append({'c': [{'v': format_jsdate(ts, tz)}, {'v': float(value)}]})

    measurements = Measurement.since(identifier, type_, since).fetch()
    for measurement in measurements[::-1]:
        ts = measurement.timestamp
        ts = ts.replace(tzinfo=pytz.timezone('UTC')) # Datastore is in UTC
        rows.append({'c':[{'v':format_jsdate(ts,tz)},{'v':float(measurement.value)}]})
    result['rows'] = rows

    if callback:
        # if we have a callback we are in JSONP mode
        return callback+"("+json.dumps(result)+")"
    else:
        return json.dumps(result)


@app.route('/insert-testdata')
def insert_testdata():
    """
        Insert test data
    """
    now = datetime.datetime.now(pytz.timezone("UTC"))
    interval = datetime.timedelta(minutes=5)
    number = 117
    ts = now - number * interval
    while ts < now:
        #measurement = Measurement(identifier='TEST-ID', type='test', value="%.2f" % random.gauss(1,0.05), timestamp = ts.replace(tzinfo=None))
        #measurement.put()
        do_publish('TEST-ID', 'test', "%.2f" % random.gauss(1,0.05), ts.replace(tzinfo=None))
        ts += interval
    return "Ok."

@app.errorhandler(404)
def page_not_found(e):
    """Return a custom 404 error."""
    return 'Sorry, nothing at this URL.', 404
