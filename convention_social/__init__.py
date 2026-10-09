"""cki-convention-social: the marketing suite for a convention and event
photography company (the public name lives in config.BRAND_NAME and can change
with one line in .env).

Package layout: core/ (config, secrets, db, settings, logs, runner, mail,
notify, state_io, auth), drive/ (the read-only photo library scanner), ai/
(Claude drafting and the monthly spend cap), buffer/ (the one publisher),
render/ (post designs built around the photos), agents/ (one module per
agent), dashboard/ (the review UI), cli.py (`bin/ccs`). Every agent that sends
or publishes is dry run until a switch on the dashboard says otherwise.
"""
__version__ = "0.1.0"
