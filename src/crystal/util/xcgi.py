

# NOTE: py2app doesn't appear to bundle the email.message module correctly,
#       which is used by the Python 3.11+ version of parse_header().
#       
#       Currently this doesn't matter because release builds of Crystal
#       are compiled with Python 3.8, but may matter in the future.
def parse_header(mime_header_value: str) -> tuple[str, dict]:
    """
        Parse a MIME header (such as Content-Type) into a main value and
        a dictionary of parameters.
        """
    from email.message import EmailMessage
    msg = EmailMessage()
    msg['content-type'] = mime_header_value
    return (msg.get_content_type(), msg['content-type'].params)
