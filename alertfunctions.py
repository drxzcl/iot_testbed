from google.appengine.api import mail
from google.appengine.api import app_identity


def send_email(measurement, params):
    sender = '{}@appspot.gserviceaccount.com'.format(app_identity.get_application_id())
    m = {'identifier': measurement.identifier, 'value': measurement.value}
    mail.send_mail(sender=params['from'], to=params['to'], subject=params.get('subject','') % m,
                   body=params.get('body','') % m)
