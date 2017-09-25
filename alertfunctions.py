from google.appengine.api import mail


def send_email(measurement, params):
    m = {'identifier': measurement.identifier, 'value': measurement.value, 'period': measurement.period}
    mail.send_mail(sender=params['from'], to=params['to'], subject=params.get('subject', '') % m,
                   body=params.get('body', '') % m)
