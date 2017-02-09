from flask import Flask, request, render_template, redirect

app = Flask(__name__)
app.config['DEBUG'] = True
from google.appengine.ext import ndb

import json
import pytz
import datetime
import random

# Note: We don't need to call run() since our application is embedded within
# the App Engine WSGI application server.

@app.route('/')
def hello():
    # Redirect to a chart
    return redirect("/chart/zomgbox-C1EB/temp", code=302)


@app.route('/chart/<identifier>/<type_>')
def chart(identifier, type_):
    return render_template('chart.template.html', id = identifier, type = type_)


class Measurement(ndb.Model):
    """Models an individual Guestbook entry with content and date."""
    timestamp = ndb.DateTimeProperty(auto_now_add=True)
    identifier = ndb.StringProperty()
    type = ndb.StringProperty()
    value = ndb.StringProperty()

    # @classmethod
    # def query_book(cls, ancestor_key):
    #     return cls.query(ancestor=ancestor_key).order(-cls.date)


@app.route('/publish')
def publish():
    secret = request.args.get('secret')
    identifier = request.args.get('id')
    for key, value in request.args.iteritems():
        if key in ("id", "secret"):
            continue
        measurement = Measurement(identifier=identifier, type=key, value=value)
        measurement.put()
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


@app.route('/getdata')
def getdata():
    identifier = request.args.get('id')
    type_ = request.args.get('type')
    callback = request.args.get('callback')
    tz = request.args.get('tz','UTC')
    tz = pytz.timezone(tz)
    measurements = Measurement.query(Measurement.identifier == identifier, Measurement.type == type_).order(
        -Measurement.timestamp).fetch(12*12*48) # 12 every hour for two days?
    result = {}
    result['cols'] = [{'id': 'A', 'label': 'time', 'type': 'datetime'},
         {'id': 'B', 'label': '%s' % type_, 'type': 'number'}, ]
    rows = []
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
    number = 10
    ts = now - number * interval
    while ts < now:
        measurement = Measurement(identifier='TEST-ID', type='test', value="%.2f" % random.gauss(1,0.05), timestamp = ts.replace(tzinfo=None))
        measurement.put()
        ts += interval
    return "Ok."

@app.errorhandler(404)
def page_not_found(e):
    """Return a custom 404 error."""
    return 'Sorry, nothing at this URL.', 404
