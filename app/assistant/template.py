import html as html_lib

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
      <span style="font-weight:bold;color:{label_color};font-size:13px;text-transform:uppercase;">{role}</span>
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

def build_escalation_email_template(conversation_id: str, customer_email: str, parsed: dict, messages: list, last_note: dict) -> tuple[str, str]:
    intent_category = parsed.get("intentCategory", "Unknown")
    escalation_reason = parsed.get("reason", parsed.get("summary", "No reason provided"))
    parsed_block = "<br/>".join(f"<strong>{k}:</strong> {v}" for k, v in parsed.items())

    thread_rows = ""

    if last_note:
        note_text = html_lib.escape(last_note.get("text", "").strip())
        note_ts = last_note.get("timestamp", "")
        
        thread_rows += thread_row_content.format(
            bg="#f0f0f0",  # Neutral gray for system/form intake
            label_color="#555",
            role="Form Submission",
            timestamp=note_ts,
            subject_line_html="<div style='font-size:12px;color:#888;margin-bottom:4px;'>Source: Website Lead Form</div>",
            body=note_text,
        )

    for msg in messages:
        role = msg.get("role", "unknown").capitalize()
        timestamp = msg.get("timestamp", "")
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
            timestamp=timestamp,
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