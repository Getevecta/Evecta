# Per-user cap on successful email sends per UTC day, counted across ALL of
# the user's campaigns. Enforced at send time in app.tasks.mail_job and used
# by the campaign insight service to project completion dates — both must
# import it from here so the gate and the estimate never drift apart.
DAILY_EMAIL_LIMIT = 50

# Gap between consecutive campaign sends for the same user (launch schedule
# + dispatcher countdown). Keeps SMTP from bursting all messages at once.
SEND_STAGGER_SECONDS = 60
