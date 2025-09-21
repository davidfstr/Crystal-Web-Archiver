from collections.abc import Callable
from functools import cache
from textwrap import dedent
from crystal.util.fastsoup import FastSoup, Tag
from crystal.util.minify import minify_js


FOOTER_BANNER_ID = 'cr-footer-banner'
_FOOTER_BANNER_MESSAGE = 'This page was archived with Crystal'


def create_footer_banner(html: FastSoup, get_request_url: Callable[[str], str]) -> Tag:
    from crystal.server.special_pages import (
        CRYSTAL_APP_URL,
        CRYSTAL_APPICON_IMAGE_URL,
        STANDARD_FONT_FAMILY,
    )
    
    a = html.new_tag('a')
    html.tag_attrs(a)['id'] = FOOTER_BANNER_ID
    html.tag_attrs(a)['href'] = CRYSTAL_APP_URL
    # Open in new window because target site - likely GitHub - may
    # refuse to load inside an iframe/frame, which we might be in
    html.tag_attrs(a)['target'] = '_blank'
    html.tag_attrs(a)['style'] = _FOOTER_BANNER_STYLE()
    
    img = html.new_tag('img')
    html.tag_attrs(img)['src'] = get_request_url(CRYSTAL_APPICON_IMAGE_URL)
    html.tag_attrs(img)['width'] = '24'
    html.tag_attrs(img)['height'] = '24'
    html.tag_attrs(img)['onerror'] = "this.style['display'] = 'none';"
    html.tag_append(a, img)
    
    span = html.new_tag('span', text_content=_FOOTER_BANNER_MESSAGE)
    html.tag_append(a, span)
    
    script = html.new_tag('script', text_content=_FOOTER_BANNER_JS())
    html.tag_append(a, script)
    
    return a


@cache
def _FOOTER_BANNER_STYLE():  # minified
    from crystal.server.special_pages import STANDARD_FONT_FAMILY
    return (
        'border-top: 2px #B40010 solid;'
        'background: #FFFAE1;'
        
        f'font-family: {STANDARD_FONT_FAMILY};'
        'font-variant: initial;'
        'font-weight: initial;'
        'text-transform: none;'
        'font-size: 14px;'
        'color: #6c757d;'
        'line-height: 2.0;'
        
        'cursor: pointer;'
        
        'display: flex;'
        'align-items: center;'
        'justify-content: center;'
        'gap: 4px;'
        
        # Position below any floated elements
        'clear: both;'
    )


# - Hide banner if it is not at the bottom of the viewport
# - If banner too high on page, pin to bottom of viewport
# - If page too short, don't show the banner at all
_FOOTER_BANNER_UNMINIFIED_JS = dedent(
    """
    window.addEventListener('load', function() {
        const a = document.querySelector('#cr-footer-banner');
        if (!a) { return; }
        
        // Hide banner if it is not at the bottom of the viewport
        if (window !== window.top) {
            let atBottomOfViewport = false;
            if (window.name) {
                const embedElements = window.parent.document.getElementsByName(window.name);
                if (embedElements.length === 1) {
                    const embedElement = embedElements[0];
                    if (embedElement.tagName === 'FRAME' &&
                        embedElement.parentElement.tagName === 'FRAMESET')
                    {
                        let curFrameOrFrameset = embedElement;
                        while (true) {
                            if (curFrameOrFrameset.parentElement.tagName !== 'FRAMESET') {
                                atBottomOfViewport = true;
                                break;
                            }
                            if (curFrameOrFrameset.parentElement.attributes['rows'] !== undefined) {
                                const rows_ = curFrameOrFrameset.parentElement.children;
                                if (curFrameOrFrameset === rows_[rows_.length - 1]) {
                                    curFrameOrFrameset = curFrameOrFrameset.parentElement;
                                    continue;
                                } else {
                                    break;
                                }
                            } else if (curFrameOrFrameset.parentElement.attributes['cols'] !== undefined) {
                                const cols_ = Array.from(curFrameOrFrameset.parentElement.children);
                                const colIndex = cols_.indexOf(curFrameOrFrameset);
                                if (colIndex === -1) {
                                    break;
                                }
                                const colSizeStrs = curFrameOrFrameset.parentElement.attributes['cols'].value.split(',');
                                const colSizeInts = colSizeStrs.map((s) => parseInt(s.trim()));
                                if (colSizeStrs[colIndex].trim() === '*' ||
                                    colSizeInts[colIndex] === Math.max.apply(null, colSizeInts))
                                {
                                    curFrameOrFrameset = curFrameOrFrameset.parentElement;
                                    continue;
                                } else {
                                    break;
                                }
                            } else {
                                // Frameset not defining rows or cols
                                break;
                            }
                        }
                    }
                }
            }
            
            if (!atBottomOfViewport) {
                a.style['display'] = 'none';
            }
        }
        
        // If banner too high on page, pin to bottom of viewport
        const aRect = a.getBoundingClientRect();
        const bannerTooHigh = (aRect.y < window.innerHeight - aRect.height);
        if (bannerTooHigh) {
            // Pin to bottom of viewport
            a.style['position'] = 'fixed';
            a.style['bottom'] = '0';
            a.style['left'] = '0';
            a.style['right'] = '0';
            
            // Stack on top
            a.style['z-index'] = '9999';
        }
        
        // If page too short, don't show the banner at all
        const pageTooShort = (
            document.body.getBoundingClientRect().height <
            aRect.height * 2
        );
        if (pageTooShort) {
            a.style['display'] = 'none';
        }
    });
    """
).strip()


@cache
def _FOOTER_BANNER_JS() -> str:
    return minify_js(_FOOTER_BANNER_UNMINIFIED_JS)


def FOOTER_IMAGE_URLS() -> list[str]:
    from crystal.server.special_pages import CRYSTAL_APPICON_IMAGE_URL
    return [
        CRYSTAL_APPICON_IMAGE_URL,
    ]
