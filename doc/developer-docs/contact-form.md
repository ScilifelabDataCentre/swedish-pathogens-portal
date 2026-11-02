# Contact form

The public contact form sends visitors' messages to the Portal team by email.

## How it works

Wagtail serves the form through a published Contact page beneath the Home page.
The fields are defined in Python: name, email, one or more categories, and a
message. Categories describe the enquiry; they do not change its recipient.

On submission, the [form](../../cms/forms/contact.py) validates the fields and
checks for spam using a hidden honeypot field, a signed timestamp, and a token
that must match a browser cookie. Visitors must wait at least two seconds before
submitting. Django's CSRF protection also applies.

The [handler](../../cms/views/contact.py) sends one plain-text email containing
the submitted details and the page URL. Sending happens during the request, so
the visitor waits for the mail backend to respond:

- **Success:** the visitor is redirected to the page with a confirmation message
  (HTTP 302).
- **Invalid submission or sending failure:** the form is shown again with the
  entered values and errors (HTTP 200). A sending failure shows a generic error.
  Anti-spam tokens are refreshed, so the visitor must wait two seconds before
  retrying.

Submissions are not saved in the database or a Wagtail submissions inbox. There
is no background queue or automatic retry; the visitor must resubmit after a
failure. Wagtail preview does not send email.

## Email configuration

`DEFAULT_FROM_EMAIL` sets the sender and `CONTACT_RECIPIENT_EMAIL` sets the
recipient. Both are required in production. The visitor's email address becomes
Reply-To, so the team can reply directly. The subject is
`[Contact] Contact and suggestions form`. No acknowledgement email is sent to
the visitor.

See [Getting started — email](getting-started.md#email-local-and-production) for
SMTP configuration and local Mailpit setup. To check the form locally, submit
synthetic details through the published page and confirm the message in Mailpit
and the success event in the application logs.

## Troubleshooting

Search the application's **stdout logs** for **`contact_submit`**, emitted by
logger **`cms.views.contact`**. Locally, these appear in the Django terminal or
the Docker `web` service logs. Each handled submission records one outcome:

- **`outcome=success` (INFO):** the mail backend returned without an exception.
- **`outcome=blocked` (WARNING):** validation or an anti-spam check rejected the form.
- **`outcome=error` (ERROR):** sending raised an exception; the reason is
  `EMAIL_SEND_ERROR`.

For example, with timestamps and other metadata omitted:

```text
[error] event=contact_submit outcome=error [cms.views.contact] duration_ms=10012 reason=EMAIL_SEND_ERROR
```

`duration_ms` measures validation and sending time. Use `request_id`, when
present, to find related request logs. **HTTP 200 does not mean the message was
sent:** both blocked submissions and caught sending failures return 200.

| Reason | Meaning | What to check |
|--------|---------|---------------|
| `HONEYPOT_HIT` | The hidden `website` field was filled. | Check for bot submissions or browser autofill. |
| `TOKEN_BAD_SIGNATURE` | The signed timestamp is missing, invalid, or expired. | Reload the page to obtain fresh tokens. |
| `TOKEN_MISMATCH` | The anti-spam cookie is missing or differs from the submitted token. | Check cookies are enabled; reload the form in one tab. |
| `TOO_FAST` | Submitted less than two seconds after token creation. | Wait two seconds, including after an error. |
| `VALIDATION_ERROR` | A form field failed validation. | Read the form's error feedback; check required fields, lengths, HTML, and link limits in the form source. |
| `EMAIL_SEND_ERROR` | The mail backend raised an exception. | Check sender, recipient, SMTP settings, and connectivity to the relay. |

Contact events omit submitted names, email addresses, message contents, and
exception details. For a sending failure, use mail-server logs or reproduce
locally with synthetic input; there is no SMTP traceback in the contact event.

If there is no contact event, inspect surrounding request logs for the reported
time and URL. A CSRF rejection returns 403 before reaching the handler; check
`django.security.csrf` warnings.

A success event does not guarantee inbox delivery. If mail is missing, check the
configured recipient, mailbox filtering, and relay delivery records. There is no
saved submission to recover from the CMS.
