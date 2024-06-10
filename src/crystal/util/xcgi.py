from email.message import EmailMessage
from typing import Dict, Tuple


def parse_header(mime_header_value: str) -> Tuple[str, Dict]:
    """
    Parse a MIME header (such as Content-Type) into a main value and
    a dictionary of parameters.
    """
    msg = EmailMessage()
    msg['content-type'] = mime_header_value
    return (msg.get_content_type(), msg['content-type'].params)
