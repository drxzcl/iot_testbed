from flask import Flask, request

app = Flask(__name__)
app.config['DEBUG'] = True
from google.appengine.ext import ndb

import json


# Note: We don't need to call run() since our application is embedded within
# the App Engine WSGI application server.

@app.route('/')
def hello():
    """Return a friendly HTTP greeting."""
    return 'Hello World!'


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


@app.route('/getdata')
def getdata():
    identifier = request.args.get('id')
    type_ = request.args.get('type')
    callback = request.args.get('callback')
    measurements = Measurement.query(Measurement.identifier == identifier, Measurement.type == type_).order(
        -Measurement.timestamp).fetch(12*12*48) # 12 every hour for two days?
    result = {}
    result['cols'] = [{'id': 'A', 'label': 'time', 'type': 'datetime'},
         {'id': 'B', 'label': '%s' % type_, 'type': 'number'}, ]
    rows = []
    for measurement in measurements[::-1]:
        rows.append({'c':[{'v':measurement.timestamp.strftime("Date(%Y,%m,%d,%H,%M,%S)")},{'v':float(measurement.value)}]})
    result['rows'] = rows

    if callback:
        # if we have a callback we are in JSONP mode
        return callback+"("+json.dumps(result)+")"
    else:
        return json.dumps(result)


@app.errorhandler(404)
def page_not_found(e):
    """Return a custom 404 error."""
    return 'Sorry, nothing at this URL.', 404
