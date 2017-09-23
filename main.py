import collections

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


def do_publish(identifier, type_, value, consolidate_every, ts=None):
    measurement = models.Measurement(identifier=identifier, type=type_, value=value)
    if ts is not None:
        measurement.timestamp = ts
    measurement.put()

    if consolidate_every:
        if random.random() < 1.0 / consolidate_every:  # consolidate every consolidate_every calls on average
            deferred.defer(consolidate.consolidate_measurements, identifier, type_, _queue="index-queue")


@app.route('/publish')
def publish():
    # Is this http or https?
    https = request.url.startswith('https')
    if not https:
        logging.warning('Measurements published over insecure connection!')

    secret = request.args.get('secret')
    identifier = request.args.get('id')

    # first verify if we're allowed to publish
    sensor = models.Sensor.query(models.Sensor.identifier == identifier).fetch()
    if not sensor or sensor[0].secret != secret:
        return "Please specify the correct secret!", 403

    # then publish the data to the specified channels.
    for key, value in request.args.iteritems():
        if key in ("id", "secret"):
            continue
        do_publish(identifier, key, value, sensor[0].consolidate_every)

    if not https:
        return "Please connect over https. Support for http will go away soon."
    return "Ok."


@app.route('/show')
def show():
    measurements = models.Measurement.query(projection=[models.Measurement.identifier, models.Measurement.type],
                                            distinct=True).fetch()
    reply = []

    charturl = "/chart/%s/%s"

    entries = []
    for measurement in measurements:
        theurl = charturl % (measurement.identifier, measurement.type)
        entries.append((theurl, measurement.identifier, measurement.type))

    return render_template('show.template.html', entries=entries)


def format_jsdate(dt, tz):
    # Format a datetime into a js Date()
    # Notice the -1 in the month.
    dt = dt.astimezone(tz)
    return "Date(%d,%d,%d,%d,%d,%d)" % (dt.year, dt.month - 1, dt.day, dt.hour, dt.minute, dt.second)


@app.route('/sensor/<identifier>')
def sensor_id(identifier):
    sensor = models.Sensor.query(models.Sensor.identifier == identifier).fetch()
    if not sensor:
        return "No such sensor", 404
    sensor = sensor[0]
    if not sensor.name:
        sensor.name = sensor.identifier
    return render_template('sensor.template.html', sensor=sensor)


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


@app.route('/getlast/<identifier>/<type_>')
def get_last(identifier, type_):
    callback = request.args.get('callback')

    last_value = None
    last = models.Measurement.last(identifier, type_).fetch(1)
    if last:
        last_value = last[0].value

    # If we have nothing, try the blocks
    if not last_value:
        last_block = models.MeasurementBlock.last_block(identifier, type_).fetch(1)
        if last_block:
            measurements = json.loads(last_block[0].values)
            last_value = measurements[-1][1]

    if last_value:
        last_value = float(last_value)

    if callback:
        # if we have a callback we are in JSONP mode
        return callback + "(" + json.dumps(last_value) + ")"
    else:
        return json.dumps(last_value)


@app.route('/tasks/alerts')
def alerts():
    """
        Process alerts
    """
    now = datetime.datetime.utcnow()
    for alert in models.Alert.query().fetch():
        if alert.last_triggered + datetime.timedelta(seconds=alert.cooldown) > now:
            continue
        # Check if alerts is triggered
        measurements = models.Measurement.last(alert.identifier, alert.type).fetch(1)
        if not measurements:
            continue
        measurement = measurements[0]

        # Add a synthetic measurement for the time since last entry
        logging.info(measurement.timestamp)
        measurement.period = "%.2f hours" % (((now - measurement.timestamp).total_seconds()) / 3600.0)
        logging.info('Last measurement for %s/%s was %s ago.' % (alert.identifier, alert.type, measurement.period))

        if alert.alert_type == "value":
            if (alert.higher and (float(measurement.value) > float(alert.value))) or \
                    (not alert.higher and (float(measurement.value) < float(alert.value))):
                # alert!
                funcname, params = json.loads(alert.alertfunction)
                func = getattr(alertfunctions, funcname)
                func(measurement, params)
                # update the alert
                alert.last_triggered = now
                alert.put()
        elif alert.alert_type == "last_entry":
            if alert.higher and (measurement.timestamp + datetime.timedelta(seconds=int(alert.value)) > now):
                # Alert!
                funcname, params = json.loads(alert.alertfunction)
                func = getattr(alertfunctions, funcname)
                func(measurement, params)
                # update the alert
                alert.last_triggered = now
                alert.put()

    return "Ok."


@app.route('/tasks/consolidate')
def tasks_consolidate():
    """
        Process consolidations
    """

    measurements = models.Measurement.query(projection=[models.Measurement.identifier, models.Measurement.type],
                                            distinct=True).fetch()

    measurements_by_sensor = collections.defaultdict(set)

    for measurement in measurements:
        measurements_by_sensor[measurement.identifier].add(measurement.type)
        consolidate.consolidate_measurements(measurement.identifier, measurement.type)

    # Update the measurement list in the sensor entry
    for identifier in measurements_by_sensor.keys():
        sensor = models.Sensor.query(models.Sensor.identifier == identifier).fetch()
        if not sensor:
            logging.warning('Sensor %r has measurements but no sensor entry!' % identifier)
            continue
        sensor = sensor[0]
        l = len(sensor.measurements)
        sensor.measurements = list(set(sensor.measurements).union(measurements_by_sensor[identifier]))
        if len(sensor.measurements) > l:
            sensor.put()

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
    # sensor = models.Sensor(identifier="TEST-ID", secret="")
    # sensor.put()
    while ts < now:
        for t in ['test', 'tust', 'tost']:
            do_publish('TEST-ID', t, "%.2f" % random.gauss(1, 0.05), 0, ts=ts.replace(tzinfo=None))
        ts += interval
    return "Ok."


@app.route('/manage/sensor/<identifier>')
def manage_sensor(identifier):
    return identifier


@app.errorhandler(404)
def page_not_found(e):
    """Return a custom 404 error."""
    return 'Sorry, nothing at this URL.', 404
