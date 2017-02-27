from flask import Flask, request, render_template, redirect
from google.appengine.ext import deferred

import json
import pytz
import datetime
import random
import time
import logging

import models
import consolidate
import alertfunctions

app = Flask(__name__)
app.config['DEBUG'] = True


@app.route('/')
def hello():
    # Redirect to the "show" url
    return redirect("/show", code=302)


@app.route('/chart/<identifier>/<type_>')
def chart(identifier, type_):
    since = request.args.get('since', str(int(time.time()) - 24 * 60 * 60))  # Last 24 hrs
    return render_template('chart.template.html', id=identifier, type=type_, since=since)


def do_publish(identifier, type_, value, ts=None):
    measurement = models.Measurement(identifier=identifier, type=type_, value=value)
    if ts is not None:
        measurement.timestamp = ts
    measurement.put()

    if random.random() < 0.08:  # A bit more than 1/15
        logging.info("Starting indexing on %s %s" % (identifier, type_))
        deferred.defer(consolidate.consolidate_measurements, identifier, type_, _queue="index-queue")


@app.route('/publish')
def publish():
    secret = request.args.get('secret')
    identifier = request.args.get('id')

    # first verify if we're allowed to publish
    sensor = models.Sensor.query(models.Sensor.identifier == identifier).fetch()
    if not sensor or sensor.secret != secret:
        return "Please specify the correct secret!", 403

    # then publish the data to the specified channels.
    for key, value in request.args.iteritems():
        if key in ("id", "secret"):
            continue
        do_publish(identifier, key, value)
    return "Ok."


@app.route('/show')
def show():
    measurements = models.Measurement.query(projection=[models.Measurement.identifier, models.Measurement.type],
                                            distinct=True).fetch()
    reply = []

    charturl = "/chart/%s/%s"

    for measurement in measurements:
        theurl = charturl % (measurement.identifier, measurement.type)
        reply.append("<a href='%s'>%s (%s)</a><BR>" % (theurl, measurement.identifier, measurement.type))
    return "\n".join(reply)


def format_jsdate(dt, tz):
    # Format a datetime into a js Date()
    # Notice the -1 in the month.
    dt = dt.astimezone(tz)
    return "Date(%d,%d,%d,%d,%d,%d)" % (dt.year, dt.month - 1, dt.day, dt.hour, dt.minute, dt.second)


@app.route('/getdata')
def getdata():
    identifier = request.args.get('id')
    type_ = request.args.get('type')
    callback = request.args.get('callback')
    tz = request.args.get('tz', 'UTC')
    tz = pytz.timezone(tz)
    since = request.args.get('since', str(int(time.time()) - 24 * 60 * 60))  # Last 24 hrs
    since = datetime.datetime.fromtimestamp(int(since), pytz.timezone('UTC'))

    result = {}
    result['cols'] = [{'id': 'A', 'label': 'time', 'type': 'datetime'},
                      {'id': 'B', 'label': '%s' % type_, 'type': 'number'}, ]
    rows = []

    blocks = models.MeasurementBlock.query(models.MeasurementBlock.identifier == identifier,
                                           models.MeasurementBlock.type == type_,
                                           models.MeasurementBlock.last > since).order(
        models.MeasurementBlock.last).fetch()
    for block in blocks:
        logging.info('Reading from block %r' % block.key)
        for ts, value in json.loads(block.values):
            ts = datetime.datetime.utcfromtimestamp(ts).replace(tzinfo=pytz.timezone('UTC'))
            if ts > since:
                rows.append({'c': [{'v': format_jsdate(ts, tz)}, {'v': float(value)}]})

    measurements = models.Measurement.since(identifier, type_, since).fetch()
    for measurement in measurements[::-1]:
        ts = measurement.timestamp
        ts = ts.replace(tzinfo=pytz.timezone('UTC'))  # Datastore is in UTC
        rows.append({'c': [{'v': format_jsdate(ts, tz)}, {'v': float(measurement.value)}]})
    result['rows'] = rows

    if callback:
        # if we have a callback we are in JSONP mode
        return callback + "(" + json.dumps(result) + ")"
    else:
        return json.dumps(result)


@app.route('/tasks/alerts')
def alerts():
    """
        Process alerts
    """
    logging.info("Alerts running")

    now = datetime.datetime.utcnow()
    for alert in models.Alert.query().fetch():
        logging.info("Alert: %r" % alert)
        if alert.last_triggered + datetime.timedelta(seconds=alert.cooldown) > now:
            continue
        # Check if alerts is triggered
        measurements = models.Measurement.last(alert.identifier, alert.type).fetch(1)
        if not measurements:
            continue
        measurement = measurements[0]
        if (alert.higher and (float(measurement.value) > float(alert.value))) or \
                (not alert.higher and (float(measurement.value) < float(alert.value))):
            # alert!
            funcname, params = json.loads(alert.alertfunction)
            func = getattr(alertfunctions, funcname)
            func(measurement, params)
            # update the alert
            alert.last_triggered = now
            alert.put()

    return "Ok."


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
        do_publish('TEST-ID', 'test', "%.2f" % random.gauss(1, 0.05), ts.replace(tzinfo=None))
        ts += interval
    return "Ok."


@app.route('/manage/sensor/<identifier>')
def manage_sensor(identifier):
    return identifier


@app.errorhandler(404)
def page_not_found(e):
    """Return a custom 404 error."""
    return 'Sorry, nothing at this URL.', 404
