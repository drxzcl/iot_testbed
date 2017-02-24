from google.appengine.ext import ndb


class Measurement(ndb.Model):
    timestamp = ndb.DateTimeProperty(auto_now_add=True)
    identifier = ndb.StringProperty()
    type = ndb.StringProperty()
    value = ndb.StringProperty()

    @classmethod
    def last(cls, identifier, type_):
        return cls.query(cls.identifier == identifier, cls.type == type_).order(-cls.timestamp)

    @classmethod
    def since(cls, identifier, type_, since):
        return cls.query(cls.identifier == identifier, cls.type == type_, cls.timestamp > since).order(cls.timestamp)

    @classmethod
    def all(cls, identifier, type_):
        return cls.query(cls.identifier == identifier, cls.type == type_).order(cls.timestamp)


class MeasurementBlock(ndb.Model):
    first = ndb.DateTimeProperty()
    last = ndb.DateTimeProperty()
    identifier = ndb.StringProperty()
    type = ndb.StringProperty()
    count = ndb.IntegerProperty()
    values = ndb.TextProperty()

    @classmethod
    def since(cls, identifier, type_, count, since):
        return cls.query(cls.identifier == identifier, cls.type == type_, cls.count == count, cls.last > since).order(
            cls.first)


class Alert(ndb.Model):
    identifier = ndb.StringProperty()
    type = ndb.StringProperty()
    value = ndb.StringProperty()
    last_triggered = ndb.DateTimeProperty()
    cooldown = ndb.IntegerProperty()
