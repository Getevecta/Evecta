"""Visible unsubscribe UI in campaign email HTML (header bar + footer)."""


def build_top_unsubscribe_html(confirm_url: str) -> str:
    """Gmail-style Unsubscribe link at the top-right of the email body."""
    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 20px 0; border-bottom: 1px solid #e8eaed;">
      <tr>
        <td align="right" style="padding: 0 0 12px 0; font-family: 'Google Sans', Roboto, Arial, sans-serif; font-size: 13px; line-height: 20px;">
          <a href="{confirm_url}" style="color: #1a73e8; text-decoration: none; font-weight: 500;">Unsubscribe</a>
        </td>
      </tr>
    </table>
    """
