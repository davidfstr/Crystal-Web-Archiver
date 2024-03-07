from urllib.parse import urlparse


def urlpatternparse(url: str):
    result = urlparse(url.replace('#', '%00'))
    return result._replace(path=result.path.replace('%00', '#'))
