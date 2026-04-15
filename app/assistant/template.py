import html as html_lib
from dateutil import parser, tz

content = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>CarClinch Email</title>
</head>

<body style="margin:0; padding:0; background:#f4f6f8; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">

<div style="max-width:600px; margin:0 auto; padding:24px;">
  <div style="border-radius:10px; border:1px solid #e1e5ea; overflow:hidden;">

    <!-- Header -->
    <div style="background-color:#f9fff7;  padding:20px 24px; color:black;">
      <div style="font-size:22px; font-weight:700;">CarClinch</div>
      <div style="font-size:12px; opacity:0.9;">Smarter car buying, less hassle.</div>
    </div>

    <!-- Body -->
    <div style="padding:24px;">

      {customer}

    </div>

    <!-- Footer -->
    <div style="padding:16px 24px; font-size:11px; color:#9ca3af; border-top:1px solid #e5e7eb; line-height:1.6;">
      You’re receiving this email because you requested information about a vehicle on CarClinch.
      If this wasn’t you, you can safely ignore this message.
    </div>

  </div>
</div>

</body>
</html>
"""
escalation_content = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Escalation Alert</title>
</head>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<div style="max-width:700px;margin:0 auto;padding:24px;">

  <div style="background:#c0392b;padding:16px 20px;border-radius:8px 8px 0 0;">
    <h2 style="margin:0;color:#fff;font-size:18px;">&#9888; Escalation Required — Manual Takeover Needed</h2>
    <p style="margin:6px 0 0;color:#f5c6c2;font-size:13px;">
      Conversation ID: <strong>{conversation_id}</strong> &nbsp;|&nbsp;
      Customer: <strong>{customer_email}</strong>
    </p>
  </div>

  <div style="background:#fff8f7;border:1px solid #f0c4bc;border-top:none;padding:16px 20px;border-radius:0 0 8px 8px;margin-bottom:20px;">
    <h3 style="margin:0 0 8px;font-size:14px;color:#c0392b;">Escalation details</h3>
    <p style="margin:0 0 4px;font-size:14px;"><strong>Category:</strong> {intent_category}</p>
    <p style="margin:0 0 4px;font-size:14px;"><strong>Reason:</strong> {escalation_reason}</p>
    <details style="margin-top:10px;">
      <summary style="font-size:13px;cursor:pointer;color:#888;">Full escalation object</summary>
      <div style="margin-top:8px;padding:10px;background:#fdf0ee;border-radius:4px;font-size:13px;line-height:1.8;">
        {parsed_block}
      </div>
    </details>
  </div>

  <h3 style="font-size:14px;color:#444;margin:0 0 8px;">Conversation history</h3>
  <table style="width:100%;border-collapse:collapse;border:1px solid #e0ddd6;border-radius:8px;overflow:hidden;">
    <tbody>{thread_rows}</tbody>
  </table>

  <p style="font-size:12px;color:#aaa;margin-top:16px;text-align:center;">
    This conversation has been automatically closed. Please reply directly to the customer at {customer_email}.
  </p>

</div>
</body>
</html>
"""

thread_row_content = """
<tr>
  <td style="padding:16px;background:{bg};border-bottom:1px solid #e0ddd6;">
    <div style="margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;">
      <span style="font-weight:bold;color:{label_color};font-size:13px;text-transform:uppercase;">{role} </span>
      <span style="font-size:12px;color:#999;">{timestamp}</span>
    </div>
    {subject_line_html}
    <div style="font-size:14px;line-height:1.6;color:#333;white-space:pre-wrap;">{body}</div>
  </td>
</tr>
"""

ack_content = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>CarClinch Email</title>
</head>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:24px;">
  <div style="border-radius:10px;border:1px solid #e1e5ea;overflow:hidden;">
    <div style="background-color:#f9fff7;padding:20px 24px;color:black;">
      <div style="font-size:22px;font-weight:700;">CarClinch</div>
      <div style="font-size:12px;opacity:0.9;">Smarter car buying, less hassle.</div>
    </div>
    <div style="padding:24px;">
      {message}
    </div>
    <div style="padding:16px 24px;font-size:11px;color:#9ca3af;border-top:1px solid #e5e7eb;line-height:1.6;">
      You're receiving this email because you requested information about a vehicle on CarClinch.
      If this wasn't you, you can safely ignore this message.
    </div>
  </div>
</div>
</body>
</html>
"""

confirmation_body = """
<p style="font-size:15px;margin:0 0 16px;">You're all set for a test drive!</p>
<table style="width:100%;border-collapse:collapse;border:1px solid #e1e5ea;border-radius:8px;overflow:hidden;margin-bottom:16px;">
  <tbody>
    <tr>
      <td style="padding:10px 14px;background:#f4f6f8;font-size:13px;color:#6b7280;width:40%;font-weight:600;">Vehicle</td>
      <td style="padding:10px 14px;font-size:14px;color:#111;">{vehicle_year} {vehicle_make} {vehicle_model}</td>
    </tr>
    <tr>
      <td style="padding:10px 14px;background:#f4f6f8;font-size:13px;color:#6b7280;font-weight:600;">Date</td>
      <td style="padding:10px 14px;font-size:14px;color:#111;">{appointment_date}</td>
    </tr>
    <tr>
      <td style="padding:10px 14px;background:#f4f6f8;font-size:13px;color:#6b7280;font-weight:600;">Time</td>
      <td style="padding:10px 14px;font-size:14px;color:#111;">{appointment_time}</td>
    </tr>
  </tbody>
</table>
<p style="font-size:14px;color:#374151;margin:0;">A calendar invitation is attached to this email. We look forward to seeing you!</p>
"""

dealer_notification_body = """
<p style="font-size:15px;font-weight:600;margin:0 0 16px;">A new test drive appointment has been booked.</p>
<table style="width:100%;border-collapse:collapse;border:1px solid #e1e5ea;border-radius:8px;overflow:hidden;margin-bottom:16px;">
  <tbody>
    <tr>
      <td style="padding:10px 14px;background:#f4f6f8;font-size:13px;color:#6b7280;width:40%;font-weight:600;">Lead</td>
      <td style="padding:10px 14px;font-size:14px;color:#111;">{lead_name} &lt;{lead_email}&gt;</td>
    </tr>
    <tr>
      <td style="padding:10px 14px;background:#f4f6f8;font-size:13px;color:#6b7280;font-weight:600;">Vehicle</td>
      <td style="padding:10px 14px;font-size:14px;color:#111;">{vehicle_year} {vehicle_make} {vehicle_model}</td>
    </tr>
    <tr>
      <td style="padding:10px 14px;background:#f4f6f8;font-size:13px;color:#6b7280;font-weight:600;">Date</td>
      <td style="padding:10px 14px;font-size:14px;color:#111;">{appointment_date}</td>
    </tr>
    <tr>
      <td style="padding:10px 14px;background:#f4f6f8;font-size:13px;color:#6b7280;font-weight:600;">Time</td>
      <td style="padding:10px 14px;font-size:14px;color:#111;">{appointment_time}</td>
    </tr>
    <tr>
      <td style="padding:10px 14px;background:#f4f6f8;font-size:13px;color:#6b7280;font-weight:600;">Conversation ID</td>
      <td style="padding:10px 14px;font-size:14px;color:#111;">{conversation_id}</td>
    </tr>
  </tbody>
</table>
"""

date_table_row = """
  <tr>
    <td style="padding:6px 10px;font-size:14px;color:#111;border-bottom:1px solid #e5e7eb;">{day_name}</td>
    <td style="padding:6px 10px;font-size:14px;color:#6b7280;border-bottom:1px solid #e5e7eb;">{date_display}</td>
  </tr>
"""

time_table_row = """
  <tr>
    <td style="padding:6px 10px;font-size:14px;color:#111;border-bottom:1px solid #e5e7eb;">{time_display}</td>
  </tr>
"""

date_table_wrapper = """
<table style="width:100%;border-collapse:collapse;border:1px solid #e1e5ea;border-radius:8px;overflow:hidden;margin:8px 0;">
  <thead>
    <tr style="background:#f4f6f8;">
      <th style="padding:8px 10px;font-size:12px;color:#6b7280;text-align:left;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;">Day</th>
      <th style="padding:8px 10px;font-size:12px;color:#6b7280;text-align:left;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;">Date</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>
"""

time_table_wrapper = """
<table style="width:100%;border-collapse:collapse;border:1px solid #e1e5ea;border-radius:8px;overflow:hidden;margin:8px 0;">
  <thead>
    <tr style="background:#f4f6f8;">
      <th style="padding:8px 10px;font-size:12px;color:#6b7280;text-align:left;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;">Available Times</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>
"""


def build_date_table(iso_dates: list[str]) -> str:
    from datetime import date as date_type
    rows = ""
    for d in iso_dates:
        parsed = date_type.fromisoformat(d)
        rows += date_table_row.format(
            day_name=parsed.strftime("%A"),
            date_display=parsed.strftime("%B %d, %Y"),
        )
    return date_table_wrapper.format(rows=rows)


def build_time_table(time_labels: list[str]) -> str:
    rows = ""
    for t in time_labels:
        rows += time_table_row.format(time_display=t)
    return time_table_wrapper.format(rows=rows)


def build_confirmation_email_template(vehicle: dict, appointment_date: str, appointment_time: str) -> str:
    body = confirmation_body.format(
        vehicle_year=vehicle["year"],
        vehicle_make=vehicle["make"],
        vehicle_model=vehicle["model"],
        appointment_date=appointment_date,
        appointment_time=appointment_time,
    )
    return build_email_template(body)


def build_dealer_notification_template(lead: dict, vehicle: dict, appointment_date: str, appointment_time: str, conversation_id: str) -> str:
    body = dealer_notification_body.format(
        lead_name=f"{lead.get('fname', '')} {lead.get('lname', '')}".strip(),
        lead_email=lead.get("email", ""),
        vehicle_year=vehicle["year"],
        vehicle_make=vehicle["make"],
        vehicle_model=vehicle["model"],
        appointment_date=appointment_date,
        appointment_time=appointment_time,
        conversation_id=conversation_id,
    )
    return build_email_template(body)

def build_escalation_email_template(conversation_id: str, customer_email: str, parsed: dict, messages: list) -> tuple[str, str]:
    intent_category = parsed.get("intentCategory", "Unknown")
    escalation_reason = parsed.get("reason", parsed.get("summary", "No reason provided"))
    parsed_block = "<br/>".join(f"<strong>{k}:</strong> {v}" for k, v in parsed.items())

    thread_rows = ""

    # Define Eastern Time for the local conversion
    eastern_tz = tz.gettz("America/Toronto")

    for msg in messages:
        role = msg.get("role", "unknown").capitalize()
        raw_timestamp = msg.get("timestamp", "")
        formatted_timestamp = raw_timestamp
        if raw_timestamp:
            try:
                dt = parser.parse(raw_timestamp)
                dt_local = dt.astimezone(eastern_tz)
                formatted_timestamp = dt_local.strftime("%b %d, %Y at %I:%M %p %Z")
            except Exception:
                pass

        body = html_lib.escape(msg.get("body", "").replace("<br />", "\n").strip())
        subject_line = html_lib.escape(msg.get("subject", ""))

        bg = "#f9f3ee" if role == "Assistant" else "#f0f4fb"
        label_color = "#7a3c1e" if role == "Assistant" else "#1a3a6b"
        
        subject_line_html = (
            f"<div style='font-size:12px;color:#666;margin-bottom:4px;'>Subject: {subject_line}</div>"
            if subject_line else ""
        )

        thread_rows += thread_row_content.format(
            bg=bg,
            label_color=label_color,
            role=role,
            timestamp=formatted_timestamp,
            subject_line_html=subject_line_html,
            body=body,
        )

    email_html = escalation_content.format(
        conversation_id=conversation_id,
        customer_email=customer_email,
        intent_category=intent_category,
        escalation_reason=escalation_reason,
        parsed_block=parsed_block,
        thread_rows=thread_rows,
    )

    subject = f"[Escalation] {intent_category} — {customer_email} — ID: {conversation_id[-6:]}"
    return subject, email_html


def build_ack_email_template() -> str:
    return ack_content.format(
        message=(
            "Thank you for your message. A member of our team will be reaching out to you shortly to assist you further. We appreciate your patience!"
        )
    )

def build_email_template(customer):
    return content.format(customer=customer)