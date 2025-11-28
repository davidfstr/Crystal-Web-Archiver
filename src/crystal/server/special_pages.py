import base64
from crystal import resources
from crystal.server.api import CreateGroupFormData
from crystal.util.minify import minify_svg
from functools import cache
from html import escape as html_escape  # type: ignore[attr-defined]
import json
import os
from textwrap import dedent


# ------------------------------------------------------------------------------
# Pages

# Whether to show generic_404_page_html() when not_in_archive_html() page
# is requested. Useful for debugging the _generic_404_page_html() page.
SHOW_GENERIC_404_PAGE_INSTEAD_OF_NOT_IN_ARCHIVE_PAGE = (
    os.environ.get('CRYSTAL_USE_GENERIC_404_PAGE', 'False') == 'True'
)


def welcome_page_html() -> str:
    welcome_styles = dedent(
        """
        .cr-welcome-form {
            margin: 30px 0;
            padding: 20px;
            background: #f8f9fa;
            border-radius: 8px;
            border-left: 4px solid #4A90E2;
        }
        
        .cr-form-row {
            margin-bottom: 16px;
        }
        
        .cr-form-row__label {
            display: block;
            margin-bottom: 4px;
            font-weight: 500;
            font-size: 14px;
            color: #495057;
        }
        
        .cr-form-row__input {
            width: 100%;
            padding: 8px 12px;
            border: 2px solid #ced4da;
            border-radius: 4px;
            font-size: 14px;
            transition: border-color 0.15s ease;
            box-sizing: border-box;
        }
        
        .cr-form-row__input:focus {
            outline: none;
            border-color: #4A90E2;
            box-shadow: 0 0 0 3px rgba(74, 144, 226, 0.1);
        }
        
        .cr-form-row__input--giant {
            padding: 12px 16px;
            border: 2px solid #e9ecef;  /* more subtle */
            border-radius: 8px;
            font-size: 16px;
        }
        
        .cr-form-row__input--monospace {
            font-family: 'Monaco', 'Menlo', 'Courier New', monospace;
        }
        
        /* Dark mode styles for welcome form */
        @media (prefers-color-scheme: dark) {
            .cr-welcome-form {
                background: #404040;
                border-left: 4px solid #6BB6FF;
            }
            
            .cr-form-row__label {
                color: #e2e8f0;
            }
            
            .cr-form-row__input {
                background: #4a5568;
                border-color: #555;
                color: #e0e0e0;
            }
            
            .cr-form-row__input:focus {
                border-color: #6BB6FF;
                box-shadow: 0 0 0 3px rgba(107, 182, 255, 0.1);
            }
        }
        """
    ).strip()
    
    content_html = dedent(
        """
        <div class="cr-page__icon">🏠</div>
        
        <div class="cr-page__title">
            <strong>Welcome to Crystal</strong>
        </div>
        
        <p>Enter the URL of a page to load from the archive:</p>
        
        <div class="cr-welcome-form">
            <form action="/">
                <div class="cr-form-row">
                    <label for="cr-url-input" class="cr-form-row__label">URL</label>
                    <input type="text" id="cr-url-input" name="url" value="https://" class="cr-form-row__input cr-form-row__input--giant cr-form-row__input--monospace" />
                </div>
                <input type="submit" value="Go" class="cr-button cr-button--primary" />
            </form>
        </div>
        """
    ).strip()
    
    return _base_page_html(
        title_html='Welcome | Crystal',
        style_html=welcome_styles,
        content_html=content_html,
        script_html='',
    )


def not_found_page_html() -> str:
    content_html = dedent(
        """
        <div class="cr-page__icon">❓</div>
        
        <div class="cr-page__title">
            <strong>Page Not Found</strong>
        </div>
        
        <p>There is no page here.</p>
        <p>The requested path was not found in this archive.</p>
        
        <div class="cr-page__actions">
            <button onclick="history.back()" class="cr-button cr-button--secondary">
                ← Go Back
            </button>
            <a href="/" class="cr-button cr-button--primary">🏠 Return to Home</a>
        </div>
        """
    ).strip()
    
    return _base_page_html(
        title_html='Not Found | Crystal',
        style_html='',
        content_html=content_html,
        script_html='',
    )


# NOTE: Crystal itself prefers to serve a Not in Archive page rather than a
#       generic HTTP 404 page. However a generic HTTP 404 page is useful
#       when exporting a Crystal project. In that context a single HTTP 404 page
#       must be suitable as the HTTP 404 response for any page in the same project.
def generic_404_page_html(default_url_prefix: str | None) -> str:
    default_url_prefix_b64 = (
        base64.b64encode(default_url_prefix.encode('utf-8')).decode('ascii')
        if default_url_prefix is not None else 
        None
    )
    
    content_top_html = dedent(
        f"""
        <div class="cr-page__icon">🚫</div>
        
        <div class="cr-page__title">
            <strong>Page Not in Archive</strong>
        </div>
        
        <p>The requested page was not found in this archive.</p>
        
        {_url_box_html(
            label_html='Original URL',
            url=None
        )}
        
        <div class="cr-page__actions">
            <button onclick="history.back()" class="cr-button cr-button--secondary">
                ← Go Back
            </button>
        </div>
        """
    ).strip()
    
    from crystal.server import _REQUEST_PATH_IN_ARCHIVE_RE
    REQUEST_PATH_IN_ARCHIVE_RE_STR = _REQUEST_PATH_IN_ARCHIVE_RE.pattern
    script_html = dedent(
        # NOTE: crDefaultUrlPrefixB64 is obfuscated as base64 so that its URL-like
        #       value won't be rewritten if Crystal downloads the 404 page.
        """
        <script>
            const crDefaultUrlPrefixB64 = %(default_url_prefix_b64_json)s;
            
            // -----------------------------------------------------------------
            // URL Box
            
            // Calculate the original archive URL based on the request URL
            document.addEventListener('DOMContentLoaded', async () => {
                const loc = document.location;
                if (loc.pathname.endsWith('/404.html')) {
                    // 404 page loaded directly. No original URL exists.
                    // Leave fallback messaging in place.
                    return;
                }
                
                const requestPath = loc.pathname + loc.search;
                const siteRootPath = await locateSiteRootPath(loc.origin, requestPath);
                const siteRelRequestPath = requestPath.substring(siteRootPath.length - 1);
                
                const crDefaultUrlPrefix = (crDefaultUrlPrefixB64 !== null)
                    ? tryDecodeBase64Utf8(crDefaultUrlPrefixB64)
                    : null;
                const archiveUrl = getArchiveUrlWithDup(siteRelRequestPath, crDefaultUrlPrefix);
                if (archiveUrl === null) {
                    // Unable to resolve archive URL.
                    // Leave fallback messaging in place.
                    return;
                }
                
                // Display the original archive URL
                const urlBoxLinkDom = document.querySelector('.cr-url-box__link');
                urlBoxLinkDom.href = archiveUrl;
                urlBoxLinkDom.innerText = archiveUrl;
            });
            
            function tryDecodeBase64Utf8(b64Str) {
                try {
                    const bytes = Uint8Array.fromBase64(base64);
                    return new TextDecoder('utf-8').decode(bytes, {fatal: true});
                } catch (e) {
                    if (e instanceof SyntaxError || e instanceof TypeError) {
                        // Invalid base64 or UTF-8
                        return null;
                    } else {
                        // API unavailable: Uint8Array, TextDecoder
                        try {
                            return atob(b64Str);
                        } catch (f) {
                            if (f instanceof InvalidCharacterError) {
                                // Invalid base64 or string is not ASCII.
                                return null;
                            } else {
                                throw f;
                            }
                        }
                    }
                }
            }
            
            // Locates the path to the directory containing the exported site,
            // which also will directly contain the "404.html" page.
            async function locateSiteRootPath(origin, pathWithinSiteRoot) {
                let pathSegments = pathWithinSiteRoot.split('/').slice(1);
                pathSegments = pathSegments.slice(0, pathSegments.length - 1);
                
                // Check each directory level, starting from root, leading up to pathWithinSiteRoot.
                // Look for a "404.html" page matching this 404 page.
                for (let i = 0; i <= pathSegments.length; i++) {
                    const candidateDir = '/' + pathSegments.slice(0, i).join('/') + (i > 0 ? '/' : '');
                    const candidate404Url = origin + candidateDir + '404.html';
                    
                    let content;
                    try {
                        const response = await fetch(candidate404Url, {
                            headers: {
                                // If backend is a Crystal server,
                                // ask it to block when dynamically downloading
                                // and return the final downloaded page,
                                // rather than returning an incremental
                                // Download In Progress page (HTTP 503).
                                'X-Crystal-Block-When-Downloading': '1'
                            }
                        });
                        content = await response.text();
                    } catch (fetchError) {
                        // No 404.html page found here
                        continue;
                    }
                    
                    const match = content.match(/const crDefaultUrlPrefixB64 = ([^;]+);/);
                    if (!match) {
                        // No Crystal 404.html page found here
                        continue;
                    }
                    
                    let candidateUrlPrefixB64;
                    try {
                        candidateUrlPrefixB64 = JSON.parse(match[1]);
                    } catch (parseError) {
                        // Looks like a Crystal 404.html page, but has a bogus crDefaultUrlPrefixB64.
                        continue;
                    }
                    if (candidateUrlPrefixB64 !== crDefaultUrlPrefixB64) {
                        // Is a Crystal 404.html page but does not match this 404 page.
                        continue
                    }
                    
                    return candidateDir;
                }
                
                // Fallback to root if no matching Crystal 404 page was found
                return '/';
            }
            
            // NOTE: Duplicated in get_archive_url_with_dup() and getArchiveUrlWithDup()
            function getArchiveUrlWithDup(requestPath, defaultUrlPrefix) {
                const match = requestPath.match(/%(REQUEST_PATH_IN_ARCHIVE_RE_STR)s/);
                if (match) {
                    const scheme = match[1];
                    const rest = match[2];
                    const archiveUrl = scheme + '://' + rest;
                    return archiveUrl;
                } else {
                    // If valid default URL prefix is set, use it
                    if (defaultUrlPrefix !== null && !defaultUrlPrefix.endsWith('/')) {
                        if (!requestPath.startsWith('/')) {
                            throw new Error('Expected path to start with /');
                        }
                        return defaultUrlPrefix + requestPath;
                    } else {
                        return null;
                    }
                }
            }
            
            // -----------------------------------------------------------------
        </script>
        """ % {
            'default_url_prefix_b64_json': json.dumps(default_url_prefix_b64),
            'REQUEST_PATH_IN_ARCHIVE_RE_STR': REQUEST_PATH_IN_ARCHIVE_RE_STR.replace('/', r'\/'),
        }
    ).strip()
    
    return _base_page_html(
        title_html='Not in Archive',
        style_html=_URL_BOX_STYLES,
        content_html=content_top_html,
        script_html=script_html,
        include_brand_header=False,
    )


def not_in_archive_html(
        *, archive_url: str,
        create_group_form_data: CreateGroupFormData,
        readonly: bool,
        default_url_prefix: str | None,
        ) -> str:
    if SHOW_GENERIC_404_PAGE_INSTEAD_OF_NOT_IN_ARCHIVE_PAGE:
        return generic_404_page_html(default_url_prefix)
    
    archive_url_html_attr = archive_url
    archive_url_html = html_escape(archive_url)
    archive_url_json = json.dumps(archive_url)
    
    not_in_archive_styles = dedent(
        """
        /* ------------------------------------------------------------------ */
        /* Readonly Notice */
        
        .cr-readonly-warning {
            background: #fff3cd;
            border: 1px solid #ffeaa7;
            color: #856404;
            padding: 12px 16px;
            border-radius: 8px;
            margin: 20px 0;
            font-size: 14px;
        }
        
        @media (prefers-color-scheme: dark) {
            .cr-readonly-warning {
                background: #5a4a2d;
                border: 1px solid #8b7355;
                color: #f4d03f;
            }
        }
        
        /* ------------------------------------------------------------------ */
        /* Create Section */
        
        .cr-create-section {
            margin-top: 20px;
            padding: 16px;
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            border-radius: 8px;
        }
        
        @media (prefers-color-scheme: dark) {
            .cr-create-section {
                background: #2d3748;
                border-color: #4a5568;
            }
        }
        
        /* ------------------------------------------------------------------ */
        /* Create Root URL Form */
        
        .cr-create-root-url-form {
            border-top: 1px solid #e9ecef;
            padding-top: 16px;
            margin-top: 16px;
        }
        
        @media (prefers-color-scheme: dark) {
            .cr-create-root-url-form {
                border-color: #4a5568;
            }
        }
        
        /* ------------------------------------------------------------------ */
        /* Create Group Form */
        
        .cr-create-group-form {
            border-top: 1px solid #e9ecef;
            padding-top: 16px;
            padding-bottom: 16px;
        }
        
        @media (prefers-color-scheme: dark) {
            .cr-create-group-form {
                border-color: #4a5568;
            }
        }
        
        /* ------------------------------------------------------------------ */
        /* Action Message */
        
        .cr-action-message {
            font-size: 14px;
            font-weight: 500;
        }
        
        .cr-action-message.success {
            color: #28a745;
        }
        
        .cr-action-message.error {
            color: #dc3545;
        }
        
        /* ------------------------------------------------------------------ */
        /* Download Progress Bar (Customizations) */
        
        .cr-download-progress-bar {
            display: none;
        }
        
        .cr-download-progress-bar.show {
            display: block;
            animation: slideDown 0.6s ease-out;
        }
        
        /* ------------------------------------------------------------------ */
        /* Utility: Form Inputs */
        
        .cr-form-row {
            margin-bottom: 16px;
        }
        
        .cr-form-row__label {
            display: block;
            margin-bottom: 4px;
            font-weight: 500;
            font-size: 14px;
            color: #495057;
        }
        
        .cr-form-input-container {
            position: relative;
        }
        
        .cr-form-row__input {
            width: 100%;
            padding: 8px 12px;
            border: 2px solid #ced4da;
            border-radius: 4px;
            font-size: 14px;
            transition: border-color 0.15s ease;
            box-sizing: border-box;
        }
        
        .cr-form-row__input:focus {
            outline: none;
            border-color: #4A90E2;
            box-shadow: 0 0 0 3px rgba(74, 144, 226, 0.1);
        }
        
        .cr-form-row__help-text {
            font-size: 12px;
            color: #6c757d;
            margin-top: 4px;
        }
        
        .cr-checkbox {
            display: flex;
            align-items: center;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
        }
        
        .cr-checkbox input[type="checkbox"] {
            margin-right: 8px;
            width: 16px;
            height: 16px;
        }
        
        .cr-checkbox:has(input[type="checkbox"]:disabled) {
            cursor: not-allowed;
        }
        .cr-checkbox:has(input[type="checkbox"]:disabled) span {
            opacity: 0.5;
        }
        
        .cr-radio {
            display: flex;
            align-items: center;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
        }
        
        .cr-radio input[type="radio"] {
            margin-right: 8px;
            width: 16px;
            height: 16px;
        }
        
        .cr-radio:has(input[type="radio"]:disabled) {
            cursor: not-allowed;
        }
        .cr-radio:has(input[type="radio"]:disabled) span {
            opacity: 0.5;
        }
        
        .cr-form__section {
            margin-top: 16px;
            padding: 12px;
            background: white;
            border: 1px solid #e9ecef;
            border-radius: 4px;
        }
        
        .cr-form__section-header {
            font-weight: 500;
            margin-bottom: 8px;
            font-size: 14px;
        }
        
        .cr-form__static-text {
            font-size: 13px;
            color: #6c757d;
            margin-bottom: 8px;
        }
        
        .cr-list-ctrl {
            height: 136px;  /* Fixed height for ~8 URLs (8 * 16px line + padding) */
            overflow-y: auto;
            overflow-x: auto;
            border: 1px solid #e9ecef;
            border-radius: 4px;
            background: #f8f9fa;
            padding: 8px;
            font-family: monospace;
            font-size: 12px;
            resize: vertical;
            min-height: 136px;
        }
        
        .cr-list-ctrl-item {
            padding: 2px 0;
            color: #495057;
            white-space: nowrap;
            overflow: visible;
        }
        
        @media (prefers-color-scheme: dark) {
            .cr-form__section {
                background: #4a5568;
                border-color: #555;
            }
            
            .cr-form__section-header {
                color: #e2e8f0;
            }
            
            .cr-form__static-text {
                color: #a0aec0;
            }
            
            .cr-form-row__label {
                color: #e2e8f0;
            }
            
            .cr-form-row__input {
                background: #4a5568;
                border-color: #555;
                color: #e0e0e0;
            }
            
            .cr-form-row__input:focus {
                border-color: #6BB6FF;
                box-shadow: 0 0 0 3px rgba(107, 182, 255, 0.1);
            }
            
            .cr-form-row__help-text {
                color: #a0aec0;
            }
            
            .cr-list-ctrl {
                background: #2d3748;
                border-color: #555;
                color: #e0e0e0;
            }
            
            .cr-list-ctrl-item {
                color: #e0e0e0;
            }
        }
        
        /* ------------------------------------------------------------------ */
        /* Utility: Animations */
        
        @keyframes slideDown {
            from {
                opacity: 0;
                max-height: 0;
                margin-top: 0;
            }
            to {
                opacity: 1;
                max-height: 100px;
                margin-top: 15px;
            }
        }
        
        @keyframes slideUp {
            from {
                opacity: 1;
                max-height: 1000px;
                margin-bottom: 16px;
                padding-top: 16px;
                padding-bottom: 16px;
            }
            to {
                opacity: 0;
                max-height: 0;
                margin-bottom: 0;
                padding-top: 0;
                padding-bottom: 0px;
                overflow: hidden;
            }
        }
        
        .slide-up {
            animation: slideUp 0.6s ease-out forwards;
        }
        
        """
    ).strip()
    
    content_top_html = dedent(
        f"""
        <div class="cr-page__icon">🚫</div>
        
        <div class="cr-page__title">
            <strong>Page Not in Archive</strong>
        </div>
        
        <p>The requested page was not found in this archive.</p>
        <p>The page has not been downloaded yet.</p>
        
        {_url_box_html(
            label_html='Original URL',
            url=archive_url
        )}
        
        {
            '<div class="cr-readonly-warning">⚠️ This project is opened in read-only mode. No new pages can be downloaded.</div>' 
            if readonly else ''
        }
        """
    ).strip()
    
    content_bottom_html = dedent(
        f"""
        <div class="cr-create-section">
            <div class="cr-form-row">
                <label class="cr-radio">
                    <input type="radio" name="cr-action-type" id="cr-create-root-url-radio" value="create-root-url" {'disabled ' if readonly else ''}onchange="onActionTypeChanged()" checked>
                    <span>Create Root URL</span>
                </label>
            </div>
            
            <div class="cr-form-row">
                <label class="cr-radio">
                    <input type="radio" name="cr-action-type" id="cr-create-group-radio" value="create-group" {'disabled ' if readonly else ''}onchange="onActionTypeChanged()">
                    <span>Create Group for Similar Pages</span>
                </label>
            </div>
            
            <div class="cr-form-row">
                <label class="cr-radio">
                    <input type="radio" name="cr-action-type" id="cr-download-only-radio" value="download-only" {'disabled ' if readonly else ''}onchange="onActionTypeChanged()">
                    <span>Download Only</span>
                </label>
            </div>
            
            <div id="cr-create-root-url-form" class="cr-create-root-url-form">
                <div class="cr-form-row">
                    <label class="cr-form-row__label">Name:</label>
                    <input type="text" id="cr-root-url-name" class="cr-form-row__input" placeholder="e.g. Home">
                </div>
            </div>
            
            <div id="cr-create-group-form" class="cr-create-group-form" style="display: none;">
                <div class="cr-form-row">
                    <label class="cr-form-row__label">URL Pattern:</label>
                    <div class="cr-form-input-container">
                        <input type="text" id="cr-group-url-pattern" class="cr-form-row__input" placeholder="https://example.com/post/*" value="{html_escape(create_group_form_data['predicted_url_pattern'])}">
                        <div class="cr-form-row__help-text"># = numbers, @ = letters, * = anything but /, ** = anything</div>
                    </div>
                </div>
                
                <div class="cr-form-row">
                    <label class="cr-form-row__label">Source:</label>
                    <select id="cr-group-source" class="cr-form-row__input">
                        <!-- Source options will be populated by JavaScript -->
                    </select>
                </div>
                
                <div class="cr-form-row">
                    <label class="cr-form-row__label">Name:</label>
                    <input type="text" id="cr-group-name" class="cr-form-row__input" placeholder="e.g. Post" value="{html_escape(create_group_form_data['predicted_name'])}">
                </div>
                
                <div class="cr-form__section">
                    <div class="cr-form__section-header">Preview Members</div>
                    <div class="cr-form__static-text">Known matching URLs:</div>
                    <div id="cr-preview-urls" class="cr-list-ctrl">
                        <!-- URLs will be populated by JavaScript -->
                    </div>
                </div>
                
                <div class="cr-form__section">
                    <div class="cr-form__section-header">New Group Options</div>
                    <label class="cr-checkbox">
                        <input type="checkbox" id="cr-download-group-immediately-checkbox" checked onchange="onDownloadImmediatelyCheckboxChange()">
                        <span>Download Group Immediately</span>
                    </label>
                </div>
            </div>
            
            <div class="cr-page__actions">
                <button onclick="history.back()" class="cr-button cr-button--secondary">
                    ← Go Back
                </button>
                <button id="cr-action-button" {'disabled ' if readonly else ''}onclick="onActionButtonClicked()" class="cr-button cr-button--primary">⬇ Download</button>
                <span id="cr-action-message" class="cr-action-message"></span>
            </div>
            
            {_DOWNLOAD_PROGRESS_BAR_HTML()}
        </div>
        """
    ).strip()
    
    script_html = dedent(
        """
        <script>
            // -----------------------------------------------------------------
            // Testing: Reload (Patchable)
            
            // NOTE: Patched by tests
            window.crReload = function() {
                window.location.reload();
            };
            
            // -----------------------------------------------------------------
            // Testing: Fetch (Pausable)
            
            (function() {
                const originalFetch = window.fetch;
                async function pausableFetch(...args) {
                    while (window.crFetchPaused) {
                        await new Promise(resolve => setTimeout(resolve, 200));
                    }
                    return originalFetch.apply(window, args);
                }
                window.fetch = pausableFetch;
            })();
            
            // -----------------------------------------------------------------
            
            %(_DOWNLOAD_PROGRESS_BAR_JS)s
            
            // -----------------------------------------------------------------
            // Create Form: Action Type Radio Buttons
            
            function onActionTypeChanged() {
                updateWhichFormVisible();
                updateActionButtonTitleAndStyle();
            }
            
            // Shows/hides the appropriate form based on selected action type
            function updateWhichFormVisible() {
                const actionType = document.querySelector('input[name="cr-action-type"]:checked').value;
                const createRootUrlForm = document.getElementById('cr-create-root-url-form');
                const createGroupForm = document.getElementById('cr-create-group-form');
                const actionButton = document.getElementById('cr-action-button');
                
                if (actionType === 'create-root-url') {
                    createRootUrlForm.style.display = 'block';
                    createGroupForm.style.display = 'none';
                } else if (actionType === 'create-group') {
                    createRootUrlForm.style.display = 'none';
                    createGroupForm.style.display = 'block';
                    populateSourceDropdown();
                    updatePreviewUrls();
                } else if (actionType === 'download-only') {
                    createRootUrlForm.style.display = 'none';
                    // Skip hiding the form if it's currently animating with slide-up,
                    // since the animation will handle the hiding
                    if (!createGroupForm.classList.contains('slide-up')) {
                        createGroupForm.style.display = 'none';
                    }
                }
            }
            
            // Collapses the Create Group Form after a Create action succeeded,
            // leaving the success message visible.
            function collapseCreateGroupForm() {
                const createGroupForm = document.getElementById('cr-create-group-form');
                createGroupForm.classList.add('slide-up');
                
                // Switch to Download Only radio button
                document.getElementById('cr-download-only-radio').checked = true;
                onActionTypeChanged();
            }
            
            function updateActionTypeRadioButtonsEnabled() {
                document.getElementById('cr-create-root-url-radio').disabled = actionInProgress || createGroupActionSuccess;
                document.getElementById('cr-create-group-radio').disabled = actionInProgress || createGroupActionSuccess;
                document.getElementById('cr-download-only-radio').disabled = actionInProgress;
            }
            
            // -----------------------------------------------------------------
            // Create Root URL Form: Fields
            
            // Respond to Enter keys
            document.addEventListener('DOMContentLoaded', function() {
                const nameInput = document.getElementById('cr-root-url-name');
                nameInput.addEventListener('keydown', handleRootUrlFormKeydown);
            });
            
            function handleRootUrlFormKeydown(event) {
                if (event.key === 'Enter') {
                    // Trigger the action button
                    onActionButtonClicked();
                    
                    event.preventDefault();
                }
            }
            
            // -----------------------------------------------------------------
            // Create Root URL Form: Enabled State
            
            function updateRootUrlFormInputsEnabled() {
                const inputs = document.querySelectorAll('#cr-create-root-url-form input, #cr-create-root-url-form button');
                inputs.forEach(input => {
                    input.disabled = actionInProgress;
                });
            }
            
            // -----------------------------------------------------------------
            // Create Group Form
            
            const createGroupFormData = %(create_group_form_data_json)s;
            
            // -----------------------------------------------------------------
            // Create Group Form: Fields
            
            // Respond to Enter keys
            document.addEventListener('DOMContentLoaded', function() {
                const urlPatternInput = document.getElementById('cr-group-url-pattern');
                urlPatternInput.addEventListener('keydown', handleGroupFormKeydown);
                
                const nameInput = document.getElementById('cr-group-name');
                nameInput.addEventListener('keydown', handleGroupFormKeydown);
            });
            
            function handleGroupFormKeydown(event) {
                if (event.key === 'Enter') {
                    // Trigger the primary button, which is always a Download button
                    onActionButtonClicked();
                    
                    event.preventDefault();
                }
            }
            
            // -----------------------------------------------------------------
            // Create Group Form: Source Field
            
            function populateSourceDropdown() {
                const sourceSelect = document.getElementById('cr-group-source');
                sourceSelect.innerHTML = '';
                
                createGroupFormData.source_choices.forEach(choice => {
                    const option = document.createElement('option');
                    option.textContent = choice.display_name;
                    option.value = JSON.stringify(choice.value);
                    sourceSelect.appendChild(option);
                });
                
                // Set predicted source if available
                if (createGroupFormData.predicted_source_value) {
                    const predictedValue = JSON.stringify(createGroupFormData.predicted_source_value);
                    for (let i = 0; i < sourceSelect.options.length; i++) {
                        if (sourceSelect.options[i].value === predictedValue) {
                            sourceSelect.selectedIndex = i;
                            break;
                        }
                    }
                }
            }
            
            // -----------------------------------------------------------------
            // Create Group Form: Preview Members Section
            
            // Update Preview Member URLs in real-time as URL Pattern changes
            document.addEventListener('DOMContentLoaded', function() {
                const urlPatternInput = document.getElementById('cr-group-url-pattern');
                urlPatternInput.addEventListener('input', updatePreviewUrls);
            });
            
            async function updatePreviewUrls() {
                const urlPattern = document.getElementById('cr-group-url-pattern').value.trim();
                const previewContainer = document.getElementById('cr-preview-urls');
                
                if (!urlPattern) {
                    previewContainer.innerHTML = '<div class="cr-list-ctrl-item">Enter a URL pattern to see matching URLs</div>';
                    return;
                }
                
                // Track this request to cancel previous ones
                const requestStartTime = Date.now();
                updatePreviewUrls.lastRequestTime = requestStartTime;
                
                // Show loading state only after 200ms delay
                const loadingTimeout = setTimeout(() => {
                    // Only show loading if this request is still the latest
                    if (updatePreviewUrls.lastRequestTime === requestStartTime) {
                        previewContainer.innerHTML = '<div class="cr-list-ctrl-item">Loading preview...</div>';
                    }
                }, 200);
                
                try {
                    const response = await fetch('/_/crystal/preview-urls', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({ url_pattern: urlPattern })
                    });
                    
                    // Clear the loading timeout since we got a response
                    clearTimeout(loadingTimeout);
                    
                    // Only update UI if this request is still the latest
                    if (updatePreviewUrls.lastRequestTime !== requestStartTime) {
                        return;  // A newer request has started
                    }
                    
                    if (!response.ok) {
                        const errorData = await response.json();
                        throw new Error(errorData.error || 'Failed to fetch preview URLs');
                    }
                    
                    const result = await response.json();
                    const matchingUrls = result.matching_urls;
                    
                    if (matchingUrls.length === 0) {
                        previewContainer.innerHTML = '<div class="cr-list-ctrl-item">No matching URLs found</div>';
                    } else {
                        // Clear container and add URLs safely
                        previewContainer.innerHTML = '';
                        matchingUrls.forEach(url => {
                            const urlDiv = document.createElement('div');
                            urlDiv.className = 'cr-list-ctrl-item';
                            urlDiv.textContent = url;
                            previewContainer.appendChild(urlDiv);
                        });
                    }
                } catch (error) {
                    // Clear the loading timeout
                    clearTimeout(loadingTimeout);
                    
                    // Only update UI if this request is still the latest
                    if (updatePreviewUrls.lastRequestTime === requestStartTime) {
                        console.error('Preview URLs error:', error);
                        previewContainer.innerHTML = '<div class="cr-list-ctrl-item">Error loading preview URLs</div>';
                    }
                }
            }
            
            // -----------------------------------------------------------------
            // Create Group Form: Enabled State
            
            function updateGroupFormInputsEnabled() {
                const inputs = document.querySelectorAll('#cr-create-group-form input, #cr-create-group-form select, #cr-create-group-form button');
                inputs.forEach(input => {
                    input.disabled = actionInProgress;
                });
            }
            
            // -----------------------------------------------------------------
            // Action Button
            
            async function onActionButtonClicked() {
                const actionType = document.querySelector('input[name="cr-action-type"]:checked').value;
                
                if (actionType === 'create-root-url') {
                    // Press "Download" or "Create" button in the root form
                    await onDownloadOrCreateRootUrlButtonClicked();
                } else if (actionType === 'create-group') {
                    // Press "Download" or "Create" button in the group form
                    await onDownloadOrCreateGroupButtonClicked();
                } else if (actionType === 'download-only') {
                    await startUrlDownload(/*isRoot=*/false);
                }
            }
            
            // -----------------------------------------------------------------
            // Action Button: Download/Create Root URL
            
            async function onDownloadOrCreateRootUrlButtonClicked() {
                const name = document.getElementById('cr-root-url-name').value.trim();
                
                clearActionMessage();
                setActionInProgress(true);
                
                try {
                    // Start individual URL download (which will create the root URL automatically)
                    await startUrlDownload(/*isRoot=*/true, /*rootName=*/name);
                } finally {
                    setActionInProgress(false);
                }
            }
            
            // -----------------------------------------------------------------
            // Action Button: Download/Create Group
            
            async function onDownloadOrCreateGroupButtonClicked() {
                const urlPattern = document.getElementById('cr-group-url-pattern').value.trim();
                const sourceValue = document.getElementById('cr-group-source').value;
                const name = document.getElementById('cr-group-name').value.trim();
                const downloadGroupImmediately = document.getElementById('cr-download-group-immediately-checkbox').checked;
                
                if (!urlPattern) {
                    showActionMessage('✖️ Please enter a URL pattern.', /*isSuccess=*/false);
                    return;
                }
                
                clearActionMessage();
                setActionInProgress(true);
                
                try {
                    const createUrl = '/_/crystal/create-group';
                    const response = await fetch(createUrl, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({
                            url_pattern: urlPattern,
                            source: sourceValue ? JSON.parse(sourceValue) : null,
                            name: name,
                            download_immediately: downloadGroupImmediately
                        })
                    });
                    
                    if (!response.ok) {
                        const errorData = await response.json();
                        throw new Error(errorData.error || 'Failed to create group');
                    }
                    
                    const result = await response.json();
                    
                    // Disable only Create Group radio button
                    setCreateGroupActionSuccess(true);
                    
                    showActionMessage('✅ Group created', /*isSuccess=*/true);
                    
                    // If download was requested, start individual URL download
                    // otherwise collapse the disabled form to show only essential elements
                    if (downloadGroupImmediately) {
                        await startUrlDownload(/*isRoot=*/false, /*rootName=*/'');
                    } else {
                        collapseCreateGroupForm();
                    }
                } catch (error) {
                    console.error('Group action error:', error);
                    showActionMessage('✖️ Failed to create group', /*isSuccess=*/false);
                } finally {
                    setActionInProgress(false);
                }
            }
            
            let createGroupActionSuccess = false;
            
            function setCreateGroupActionSuccess(success) {
                createGroupActionSuccess = success;
                updateActionTypeRadioButtonsEnabled();
            }
            
            // -----------------------------------------------------------------
            // Action Button: Download Only
            
            async function startUrlDownload(isRoot, rootName/*=''*/) {
                const actionButton = document.getElementById('cr-action-button');
                
                // Disable the action button
                setActionInProgress(true);
                
                try {
                    // Start the download
                    const createUrl = '/_/crystal/create-url';
                    const requestBody = {
                        url: %(archive_url_json)s,
                        is_root: isRoot,
                        download_immediately: true,
                    };
                    if (rootName !== undefined && rootName !== '') {
                        requestBody.name = rootName;
                    }
                    const response = await fetch(createUrl, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify(requestBody)
                    });
                    if (!response.ok) {
                        const errorData = await response.json();
                        throw new Error(errorData.error || 'Failed to start download');
                    }
                    
                    if (isRoot) {
                        showActionMessage('✅ Root URL created', /*isSuccess=*/true);
                    }
                    
                    const result = await response.json();
                    const taskId = result.task_id;
                    
                    // Start progress tracking using shared functionality
                    runDownloadProgressBar(taskId, {
                        onStart: (progressText) => {
                            progressText.textContent = 'Starting download...';
                        },
                        onSuccess: () => {
                            window.crReload();
                        },
                        onError: () => {
                            setActionInProgress(false);
                        },
                        errorMessage: 'Download failed.'
                    });
                    
                } catch (error) {
                    console.error('Download error:', error);
                    
                    if (isRoot) {
                        showActionMessage('✖️ Failed to create root URL', /*isSuccess=*/false);
                    }
                    
                    // Update progress with error using shared functionality
                    const { progressFill, progressText } = showDownloadProgressBar();
                    progressFill.style.width = '0%%';
                    progressText.textContent = `Download failed: ${error.message}`;
                    
                    setActionInProgress(false);
                }
            }
            
            // -----------------------------------------------------------------
            // Action Button: State
            
            // Initialize action button on page load
            document.addEventListener('DOMContentLoaded', function() {
                updateActionButtonEnabled();
                updateActionButtonTitleAndStyle();
            });
            
            function updateActionButtonEnabled() {
                const actionButton = document.getElementById('cr-action-button');
                actionButton.disabled = actionInProgress;
            }
            
            function updateActionButtonTitleAndStyle() {
                const actionType = document.querySelector('input[name="cr-action-type"]:checked').value;
                const actionButton = document.getElementById('cr-action-button');
                if (actionType === 'create-root-url') {
                    if (!actionInProgress) {
                        actionButton.textContent = '⬇ Download';
                        actionButton.className = 'cr-button cr-button--primary';
                    } else {
                        actionButton.textContent = 'Creating & Starting Download...';
                        actionButton.className = 'cr-button cr-button--primary';
                    }
                } else if (actionType === 'create-group') {
                    const downloadImmediatelyCheckbox = document.getElementById('cr-download-group-immediately-checkbox');
                    if (!actionInProgress) {
                        if (downloadImmediatelyCheckbox.checked) {
                            actionButton.textContent = '⬇ Download';
                            actionButton.className = 'cr-button cr-button--primary';
                        } else {
                            actionButton.textContent = '✚ Create';
                            actionButton.className = 'cr-button cr-button--secondary';
                        }
                    } else {
                        if (downloadImmediatelyCheckbox.checked) {
                            actionButton.textContent = 'Creating & Starting Download...';
                            actionButton.className = 'cr-button cr-button--primary';
                        } else {
                            actionButton.textContent = 'Creating...';
                            actionButton.className = 'cr-button cr-button--secondary';
                        }
                    }
                } else if (actionType === 'download-only') {
                    if (!actionInProgress) {
                        actionButton.textContent = '⬇ Download';
                    } else {
                        actionButton.textContent = '⬇ Downloading...';
                    }
                    actionButton.className = 'cr-button cr-button--primary';
                }
            }
            
            let actionInProgress = false;
            
            function setActionInProgress(inProgress) {
                actionInProgress = inProgress;
                
                updateActionTypeRadioButtonsEnabled();
                updateRootUrlFormInputsEnabled();
                updateGroupFormInputsEnabled();
                updateActionButtonEnabled();
                updateActionButtonTitleAndStyle();
            }
            
            function onDownloadImmediatelyCheckboxChange() {
                updateActionButtonTitleAndStyle();
            }
            
            // -----------------------------------------------------------------
            // Action Message
            
            function showActionMessage(message, isSuccess) {
                const messageElement = document.getElementById('cr-action-message');
                messageElement.textContent = message;
                messageElement.className = `cr-action-message ${isSuccess ? 'success' : 'error'}`;
            }
            
            function clearActionMessage() {
                const messageElement = document.getElementById('cr-action-message');
                messageElement.textContent = '';
                messageElement.className = 'cr-action-message';
            }
            
            // -----------------------------------------------------------------
        </script>
        """ % {
            'archive_url_json': archive_url_json,
            'create_group_form_data_json': json.dumps(create_group_form_data),
            '_DOWNLOAD_PROGRESS_BAR_JS': _DOWNLOAD_PROGRESS_BAR_JS
        }
    ).strip()
    
    return _base_page_html(
        title_html='Not in Archive | Crystal',
        style_html=(
            _URL_BOX_STYLES + '\n\n' + 
            _DOWNLOAD_PROGRESS_BAR_STYLES + '\n\n' + 
            not_in_archive_styles
        ),
        content_html=(content_top_html + content_bottom_html),
        script_html=script_html,
    )


def download_in_progress_html(
        *, archive_url: str,
        task_id: str,
        default_url_prefix: str | None,
        # NOTE: Patched by tests
        ignore_reload_requests: bool=False,
        ) -> str:
    task_id_json = json.dumps(task_id)
    ignore_reload_requests_json = json.dumps(ignore_reload_requests)
    
    download_in_progress_styles = dedent(
        """
        /* ------------------------------------------------------------------ */
        /* Download Progress Bar (Customizations) */
        
        .cr-download-progress-bar {
            display: block;
        }
        """
    ).strip()
    
    content_html = dedent(
        f"""
        <div class="cr-page__icon">⬇️</div>
        
        <div class="cr-page__title">
            <strong>Download In Progress</strong>
        </div>
        
        {_DOWNLOAD_PROGRESS_BAR_HTML()}
        """
    ).strip()
    
    script_html = dedent(
        """
        <script>
            const ignoreReloadRequests = %(ignore_reload_requests_json)s;
            
            // NOTE: Patched by tests
            window.crReload = function() {
                window.crDidCallReload = true;
                if (!ignoreReloadRequests) {
                    window.location.reload();
                }
            };
            
            %(_DOWNLOAD_PROGRESS_BAR_JS)s
            
            // -----------------------------------------------------------------
            // Download Progress Polling
            
            async function startProgressPolling() {
                const taskId = %(task_id_json)s;
                
                // Start progress tracking using shared functionality
                runDownloadProgressBar(taskId, {
                    onStart: (progressText) => {
                        progressText.textContent = 'Preparing download...';
                    },
                    onSuccess: () => {
                        window.crReload();
                    },
                    onError: () => {
                        // nothing
                    },
                    errorMessage: 'Download failed.'
                });
            }
            
            // -----------------------------------------------------------------
            
            // Start polling immediately when page loads
            startProgressPolling();
        </script>
        """ % {
            'task_id_json': task_id_json,
            'ignore_reload_requests_json': ignore_reload_requests_json,
            '_DOWNLOAD_PROGRESS_BAR_JS': _DOWNLOAD_PROGRESS_BAR_JS,
        }
    ).strip()
    
    return _base_page_html(
        title_html='Download In Progress | Crystal',
        style_html=(
            _DOWNLOAD_PROGRESS_BAR_STYLES + '\n\n' + 
            download_in_progress_styles
        ),
        content_html=content_html,
        script_html=script_html,
    )


def fetch_error_html(
        *, archive_url: str,
        error_type_html: str,
        error_message_html: str,
        ) -> str:
    archive_url_json = json.dumps(archive_url)
    
    fetch_error_styles = dedent(
        """
        /* ------------------------------------------------------------------ */
        /* Download Progress Bar (Customizations) */
        
        .cr-download-progress-bar {
            display: none;
        }
        
        .cr-download-progress-bar.show {
            display: block;
            animation: slideDown 0.6s ease-out;
        }
        
        @keyframes slideDown {
            from {
                opacity: 0;
                transform: translateY(-10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        """
    ).strip()
    
    content_html = dedent(
        f"""
        <div class="cr-page__icon">⚠️</div>
        
        <div class="cr-page__title">
            <strong>Fetch Error</strong>
        </div>
        
        <p>
            A <code>{error_type_html}</code> error with message <code>{error_message_html}</code>
            was encountered when fetching this resource.
        </p>
        
        {_url_box_html(
            label_html='Original URL',
            url=archive_url,
        )}
        
        <div class="cr-page__actions">
            <button onclick="history.back()" class="cr-button cr-button--secondary">
                ← Go Back
            </button>
            <button id="cr-retry-button" onclick="onRetryDownload()" class="cr-button cr-button--primary">
                ⟳ Retry Download
            </button>
        </div>
        
        {_DOWNLOAD_PROGRESS_BAR_HTML('Preparing retry...')}
        """
    ).strip()
    
    script_html = dedent(
        """
        <script>
            // NOTE: Patched by tests
            window.crReload = function() {
                window.location.reload();
            };
            
            %(_DOWNLOAD_PROGRESS_BAR_JS)s
            
            let retryInProgress = false;
            
            function setRetryInProgress(inProgress) {
                retryInProgress = inProgress;
                
                const retryButton = document.getElementById('cr-retry-button');
                retryButton.disabled = inProgress;
                
                if (inProgress) {
                    retryButton.textContent = '⟳ Retrying...';
                    retryButton.className = 'cr-button cr-button--primary';
                } else {
                    retryButton.textContent = '⟳ Retry Download';
                    retryButton.className = 'cr-button cr-button--primary';
                }
            }
            
            async function onRetryDownload() {
                if (retryInProgress) {
                    return;
                }
                
                // Show retry in progress state
                setRetryInProgress(true);
                
                try {
                    // Start the retry download
                    const retryUrl = '/_/crystal/retry-download';
                    const requestBody = {
                        url: %(archive_url_json)s
                    };
                    const response = await fetch(retryUrl, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify(requestBody)
                    });
                    if (!response.ok) {
                        const errorData = await response.json();
                        throw new Error(errorData.error || 'Failed to start retry');
                    }
                    
                    const result = await response.json();
                    const taskId = result.task_id;
                    
                    // Start progress tracking using shared functionality
                    runDownloadProgressBar(taskId, {
                        onStart: (progressText) => {
                            progressText.textContent = 'Starting retry...';
                        },
                        onSuccess: () => {
                            window.crReload();
                        },
                        onError: () => {
                            setRetryInProgress(false);
                        },
                        errorMessage: 'Retry failed.'
                    });
                    
                } catch (error) {
                    console.error('Retry error:', error);
                    
                    // Update progress with error using shared functionality
                    const { progressFill, progressText } = showDownloadProgressBar();
                    progressFill.style.width = '0%%';
                    progressText.textContent = `Retry failed: ${error.message}`;
                    
                    setRetryInProgress(false);
                }
            }
        </script>
        """ % {
            'archive_url_json': archive_url_json,
            '_DOWNLOAD_PROGRESS_BAR_JS': _DOWNLOAD_PROGRESS_BAR_JS,
        }
    ).strip()
    
    return _base_page_html(
        title_html='Fetch Error | Crystal',
        style_html=(
            _URL_BOX_STYLES + '\n\n' + 
            _DOWNLOAD_PROGRESS_BAR_STYLES + '\n\n' + 
            fetch_error_styles
        ),
        content_html=content_html,
        script_html=script_html,
    )


# ------------------------------------------------------------------------------
# Base Page

def _base_page_html(
        *, title_html: str,
        style_html: str,
        content_html: str,
        script_html: str,
        include_brand_header: bool=True,
        ) -> str:
    # TODO: After Python 3.12+ is minimum Python version, inline this
    NEWLINE = '\n'
    page_html = dedent(
        f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8" />
            <title>{title_html}</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                {_BASE_PAGE_STYLE_TEMPLATE + NEWLINE + style_html}
            </style>
        </head>
        <body class="cr-body">
            <div class="cr-body__container">
                {_BRAND_HEADER_HTML_TEMPLATE() if include_brand_header else ''}
                
                {content_html}
            </div>
            
            {script_html}
        </body>
        </html>
        """
    ).lstrip()  # type: str
    
    # Look for common templating errors
    if '%%' in page_html:
        offset = page_html.index('%%')
        raise ValueError(f'Unescaped % in HTML template. Near: {page_html[offset-20:offset+20]!r}')
    
    return page_html


@cache
def _APPICON_FALLBACK_IMAGE_URL() -> str:
    """Data image URL with a simplified version of the app icon."""
    with resources.open_binary('appicon--fallback.svg') as f:
        svg_bytes = f.read()
    return _to_base64_url('image/svg+xml', minify_svg(svg_bytes))

def _to_base64_url(mime_type: str, svg_image_bytes: bytes) -> str:
    """
    Converts bytes to a base64-encoded data URL.

    Returns a string like: "data:image/svg+xml;base64,PHN2ZyB4bWxu...".
    """
    b64 = base64.b64encode(svg_image_bytes).decode("ascii")
    return f"data:{mime_type};base64,{b64}"


STANDARD_FONT_FAMILY = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"

_BASE_PAGE_STYLE_TEMPLATE = dedent(
    """
    .cr-body {
        font-family: %(_STANDARD_FONT_FAMILY)s;
        line-height: 1.6;
        margin: 0;
        padding: 40px 20px;
        background: linear-gradient(135deg, #f5f7fa 0%%, #c3cfe2 100%%);
        min-height: 100vh;
        box-sizing: border-box;
        color: #333;
        /* Always show vertical scrollbar to avoid layout shifts when page content changes height */
        overflow-y: scroll;
    }
    
    .cr-body__container {
        max-width: 600px;
        margin: 0 auto;
        background: white;
        border-radius: 12px;
        padding: 40px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
    }
    
    .cr-brand-header {
        border-bottom: 2px solid #e9ecef;
        margin-bottom: 30px;
    }
    
    .cr-brand-header__link {
        display: flex;
        align-items: center;
        padding-bottom: 20px;
        text-decoration: none;
    }
    
    /* Dark mode styles for top of page */
    @media (prefers-color-scheme: dark) {
        .cr-body {
            background: linear-gradient(135deg, #1a1a1a 0%%, #2d2d30 100%%);
            color: #e0e0e0;
        }
        
        .cr-body__container {
            background: #2d2d30;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
        }
        
        .cr-brand-header {
            border-bottom: 2px solid #404040;
        }
    }
    
    .cr-brand-header__logo {
        margin-right: 16px;
        flex-shrink: 0;
    }
    .cr-brand-header__logo,
    .cr-brand-header__logo--image,
    .cr-brand-header__logo--image_fallback {
        width: 48px;
        height: 48px;
    }
    
    /* Fallback to simplified inline image if full logo image not available */
    .cr-brand-header__logo--image_fallback {
        display: none;
    }
    .cr-brand-header__logo--error .cr-brand-header__logo--image_fallback {
        display: inline;
    }
    .cr-brand-header__logo--error .cr-brand-header__logo--image {
        display: none;
    }
    
    .cr-brand-header__text {
        flex: 1;
    }
    
    .cr-brand-header__title {
        margin: 0;
        height: 32px;
        line-height: 1;
    }
    
    .cr-brand-header__title img {
        height: 32px;
        width: auto;
        vertical-align: baseline;
    }
    
    /* Default to light logotext */
    .cr-brand-header__title__logotext--light {
        display: inline;
    }
    .cr-brand-header__title__logotext--dark {
        display: none;
    }
    
    /* Fallback to regular text instead of logotext if logotext images not available */
    .cr-brand-header__logotext--text {
        display: none;
        
        /* NOTE: Duplicated by _BASE_FONT_SIZE and .cr-brand-header__logotext--text font-size */
        font-size: 23px;
        /* NOTE: Duplicated by _LIGHT_TEXT_COLOR and .cr-brand-header__logotext--text color */
        color: #000;
    }
    .cr-brand-header__logotext--error .cr-brand-header__logotext--text {
        display: inline;
    }
    .cr-brand-header__logotext--error .cr-brand-header__title__logotext--light,
    .cr-brand-header__logotext--error .cr-brand-header__title__logotext--dark {
        display: none;
    }
    
    .cr-brand-header__subtitle {
        font-size: 14px;
        color: #6c757d;
        margin: 0;
    }
    
    .cr-page__icon {
        font-size: 64px;
        color: #e74c3c;
        text-align: center;
        margin: 20px 0;
    }
    .cr-page__icon:first-child {
        margin-top: 0;
    }
    
    .cr-page__title {
        font-size: 18px;
        color: #2c3e50;
        text-align: center;
        margin: 20px 0;
    }
    
    /* Dark mode styles for brand and content */
    @media (prefers-color-scheme: dark) {
        .cr-brand-header__subtitle {
            color: #a0a0a0;
        }
        
        .cr-page__title {
            color: #e0e0e0;
        }
        
        /* Switch to dark logotext */
        .cr-brand-header__title__logotext--light {
            display: none;
        }
        .cr-brand-header__title__logotext--dark {
            display: inline;
        }
        
        .cr-brand-header__logotext--text {
            /* NOTE: Duplicated by _DARK_TEXT_COLOR and @media .cr-brand-header__logotext--text color */
            color: #d8d8d8;
        }
    }
    
    .cr-page__actions {
        margin: 0 0;
    }
    
    .cr-button {
        display: inline-block;
        padding: 12px 24px;
        margin: 8px 8px 8px 0;
        border: none;
        border-radius: 8px;
        font-size: 16px;
        font-weight: 500;
        cursor: pointer;
        text-decoration: none;
        transition: all 0.2s ease;
        min-width: 120px;
        text-align: center;
        
        /* Use consistent height to avoid variance in height from emoji characters */
        height: 48px;
        box-sizing: border-box;
        line-height: 24px;
    }
    
    .cr-button--primary {
        background: #4A90E2;
        color: white;
    }
    
    .cr-button--primary:hover {
        background: #357ABD;
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(74, 144, 226, 0.3);
    }
    
    .cr-button--primary:disabled {
        opacity: 0.5;
        cursor: not-allowed;
        pointer-events: none;
    }
    
    .cr-button--primary:disabled:hover {
        background: #4A90E2;
        transform: none;
        box-shadow: none;
    }
    
    .cr-button--secondary {
        background: #6c757d;
        color: white;
    }
    
    .cr-button--secondary:hover {
        background: #5a6268;
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(108, 117, 125, 0.3);
    }
    
    .cr-button--secondary:disabled {
        opacity: 0.5;
        cursor: not-allowed;
        pointer-events: none;
    }
    
    .cr-button--secondary:disabled:hover {
        background: #6c757d;
        transform: none;
        box-shadow: none;
    }
    """
).lstrip() % dict(
    _STANDARD_FONT_FAMILY=STANDARD_FONT_FAMILY,
)


CRYSTAL_APP_URL = 'https://dafoster.net/projects/crystal-web-archiver/'

_CRYSTAL_APPICON_IMAGE_URL_REF = '/_/crystal/resources/appicon.png'
CRYSTAL_APPICON_IMAGE_URL = 'crystal://resources/appicon.png'

@cache
def _BRAND_HEADER_HTML_TEMPLATE() -> str:
    return dedent(
        f"""
        <div class="cr-brand-header">
            <a class="cr-brand-header__link" href="{CRYSTAL_APP_URL}" target="_blank">
                <span class="cr-brand-header__logo">
                    <img src="{_CRYSTAL_APPICON_IMAGE_URL_REF}" alt="Crystal icon" class="cr-brand-header__logo--image" onerror="document.querySelector('.cr-brand-header__logo').classList.add('cr-brand-header__logo--error');" />
                    <img src="{_APPICON_FALLBACK_IMAGE_URL()}" alt="Crystal icon" class="cr-brand-header__logo--image_fallback" />
                </span>
                <div class="cr-brand-header__text">
                    <h1 class="cr-brand-header__title">
                        <span class="cr-brand-header__logotext">
                            <span class="cr-brand-header__logotext--text">
                                Crystal
                            </span>
                            <img
                                src="/_/crystal/resources/logotext.png" 
                                srcset="/_/crystal/resources/logotext.png 1x, /_/crystal/resources/logotext@2x.png 2x"
                                alt="Crystal"
                                class="cr-brand-header__title__logotext--light"
                                onerror="document.querySelector('.cr-brand-header__logotext').classList.add('cr-brand-header__logotext--error');"
                            />
                            <img
                                src="/_/crystal/resources/logotext-dark.png" 
                                srcset="/_/crystal/resources/logotext-dark.png 1x, /_/crystal/resources/logotext-dark@2x.png 2x"
                                alt="Crystal"
                                class="cr-brand-header__title__logotext--dark"
                                onerror="document.querySelector('.cr-brand-header__logotext').classList.add('cr-brand-header__logotext--error');"
                            />
                        </span>
                    </h1>
                    <p class="cr-brand-header__subtitle">A Website Archiver</p>
                </div>
            </a>
        </div>
        """
    )


# ------------------------------------------------------------------------------
# URL Info Box

_URL_BOX_STYLES = dedent(
    """
    .cr-url-box {
        background: #f8f9fa;
        padding: 15px;
        border-radius: 8px;
        border-left: 4px solid #4A90E2;
        margin: 20px 0;
    }
    
    .cr-url-box__label {
        font-size: 12px;
        color: #6c757d;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 5px;
        font-weight: 600;
    }
    
    .cr-url-box__link {
        text-decoration: none;
        word-break: break-all;
        font-family: 'Monaco', 'Menlo', 'Courier New', monospace;
        font-size: 14px;
    }
    .cr-url-box__link[href] {
        color: #4A90E2;
    }
    .cr-url-box__link[href]:hover {
        text-decoration: underline;
    }
    
    /* Dark mode styles for URL */
    @media (prefers-color-scheme: dark) {
        .cr-url-box {
            background: #404040;
            border-left: 4px solid #6BB6FF;
        }
        
        .cr-url-box__label {
            color: #a0a0a0;
        }
        
        .cr-url-box__link {
            color: #6BB6FF;
        }
    }
    """
).lstrip()  # type: str


def _url_box_html(label_html: str, url: str | None) -> str:
    return dedent(
        f"""
        <div class="cr-url-box">
            <div class="cr-url-box__label">{label_html}</div>
            <a{(' href="' + url + '"') if url is not None else ''} class="cr-url-box__link" target="_blank" rel="noopener">
                {html_escape(url) if url is not None else "See browser's URL"}
            </a>
        </div>
        """
    ).strip()


# ------------------------------------------------------------------------------
# Download Progress Bar

_DOWNLOAD_PROGRESS_BAR_STYLES = dedent(
    """
    /* ------------------------------------------------------------------ */
    /* Download Progress Bar */
    
    .cr-download-progress-bar {
        margin-top: 15px;
    }
    
    .cr-download-progress-bar__outline {
        width: 100%;
        height: 8px;
        background: #e9ecef;
        border-radius: 4px;
        overflow: hidden;
    }
    
    .cr-download-progress-bar__fill {
        height: 100%;
        background: #4A90E2;
        width: 0%;
        transition: width 0.3s ease;
    }
    
    .cr-download-progress-bar__message {
        font-size: 14px;
        margin-top: 8px;
        text-align: center;
    }
    
    @media (prefers-color-scheme: dark) {
        .cr-download-progress-bar__outline {
            background: #404040;
        }
        
        .cr-download-progress-bar__fill {
            background: #6BB6FF;
        }
    }
    """
).lstrip()  # type: str


_DOWNLOAD_PROGRESS_BAR_JS = dedent(
    """
    // Download Progress Bar JavaScript
    
    let crProgressEventSource = null;
    
    function showDownloadProgressBar() {
        const progressDiv = document.getElementById('cr-download-progress-bar');
        const progressFill = document.getElementById('cr-download-progress-bar__fill');
        const progressText = document.getElementById('cr-download-progress-bar__message');
        
        // Show progress with animation
        progressDiv.style.display = 'block';
        // Force a reflow to ensure display: block is applied before adding the animation class
        progressDiv.offsetHeight;
        progressDiv.classList.add('show');
        progressFill.style.width = '0%';
        
        return { progressDiv, progressFill, progressText };
    }
    
    function runDownloadProgressBar(taskId, callbacks) {
        const progressUrl = `/_/crystal/download-progress?task_id=${encodeURIComponent(taskId)}`;
        const { progressDiv, progressFill, progressText } = showDownloadProgressBar();
        
        // Set initial message
        if (callbacks.onStart) {
            callbacks.onStart(progressText);
        } else {
            progressText.textContent = 'Starting download...';
        }
        
        crProgressEventSource = new EventSource(progressUrl);
        
        crProgressEventSource.onmessage = function(event) {
            const data = JSON.parse(event.data);
            
            if (data.error) {
                // Update progress with error
                progressFill.style.width = '0%';
                progressText.textContent = `Error: ${data.error}`;
                
                crProgressEventSource.close();
                
                if (callbacks.onError) {
                    callbacks.onError();
                }
                
                return;
            }
            
            if (data.status === 'complete') {
                // Update progress with success
                progressFill.style.width = '100%';
                progressText.textContent = 'Download completed! Reloading page...';
                
                crProgressEventSource.close();
                
                if (callbacks.onSuccess) {
                    callbacks.onSuccess();
                } else {
                    // Default behavior: reload the page
                    window.crReload();
                }
            } else if (data.status === 'in_progress') {
                progressFill.style.width = `${data.progress}%`;
                progressText.textContent = data.message;
            } else {
                console.warn(`Unknown download status: ${data.status}`);
            }
        };
        
        crProgressEventSource.onerror = function(event) {
            // Update progress with error
            progressFill.style.width = '0%';
            
            const errorMessage = callbacks.errorMessage || 'Download failed.';
            progressText.textContent = errorMessage;
            
            crProgressEventSource.close();
            
            if (callbacks.onError) {
                callbacks.onError();
            }
        };
    }
    
    // Close event source when page unloads
    window.addEventListener('beforeunload', () => {
        if (crProgressEventSource) {
            crProgressEventSource.close();
            crProgressEventSource = null;
        }
    });
    """
).strip()


def _DOWNLOAD_PROGRESS_BAR_HTML(message: str = 'Preparing download...') -> str:
    return dedent(
        f"""
        <div id="cr-download-progress-bar" class="cr-download-progress-bar">
            <div class="cr-download-progress-bar__outline">
                <div id="cr-download-progress-bar__fill" class="cr-download-progress-bar__fill"></div>
            </div>
            <div id="cr-download-progress-bar__message" class="cr-download-progress-bar__message">{html_escape(message)}</div>
        </div>
        """
    ).strip()


# ------------------------------------------------------------------------------