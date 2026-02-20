
content = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>CarClinch Email</title>

<style>
  body {{
    margin: 0;
    padding: 0;
    background: #f4f6f8;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }}

  .container {{
    max-width: 600px;
    margin: 0 auto;
    padding: 24px;
  }}

  .card {{
    background: #ffffff;
    border-radius: 10px;
    border: 1px solid #e1e5ea;
    overflow: hidden;
  }}

  .header {{
    background: linear-gradient(128deg,#000,#7cd64d);
    padding: 20px 24px;
    color: #ffffff;
  }}

  .header-title {{
    font-size: 22px;
    font-weight: 700;
  }}

  .header-sub {{
    font-size: 12px;
    opacity: 0.9;
  }}

  .body {{
    padding: 24px;
  }}

  .body p {{
    margin: 0 0 16px 0;
    font-size: 14px;
    line-height: 1.7;
    color: #4b5563;
  }}

  .body p strong {{
    color: #111827;
  }}

  .dealership-box {{
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 16px;
    margin: 16px 0;
  }}

  .dealership-title {{
    font-size: 14px;
    font-weight: 600;
    color: #0b1f33;
    margin-bottom: 8px;
  }}

  .dealership-box a {{
    color: #0f6bb8;
    text-decoration: none;
  }}

  .footer {{
    padding: 16px 24px;
    font-size: 11px;
    color: #9ca3af;
    border-top: 1px solid #e5e7eb;
    line-height: 1.6;
  }}
</style>

</head>
<body>

<div class="container">
  <div class="card">

    <!-- Header -->
    <div class="header">
      <div class="header-title">CarClinch</div>
      <div class="header-sub">Smarter car buying, less hassle.</div>
    </div>

    <!-- Body -->
    <div class="body">

      {customer}

      <!-- Dealership block -->
      <div class="dealership-box">
        <div class="dealership-title">Dealership contact details</div>

        {dealership}
      </div>

      <p>Looking forward to helping you find the right fit.</p>

      <p>
        Best,<br />
        <strong>CarClinch</strong>
      </p>

    </div>

    <!-- Footer -->
    <div class="footer">
      You’re receiving this email because you requested information about a vehicle on CarClinch.
      If this wasn’t you, you can safely ignore this message.
    </div>

  </div>
</div>
</body>
</html>
"""

def build_email_template(customer, dealership):
    return content.format(customer=customer, dealership=dealership)