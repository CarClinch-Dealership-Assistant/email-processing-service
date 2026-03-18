
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

def build_email_template(customer):
    return content.format(customer=customer)