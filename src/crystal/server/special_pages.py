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

# Whether to show _generic_404_page_html() when _not_in_archive_html() page
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
                        const response = await fetch(candidate404Url);
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
        style_html=_URL_BOX_STYLE_TEMPLATE,
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
        /* Download Progress Bar */
        
        .cr-download-progress-bar {
            display: none;
            margin-top: 15px;
        }
        
        .cr-download-progress-bar.show {
            display: block;
            animation: slideDown 0.6s ease-out;
        }
        
        .cr-progress-bar__outline {
            width: 100%;
            height: 8px;
            background: #e9ecef;
            border-radius: 4px;
            overflow: hidden;
        }
        
        .cr-progress-bar__fill {
            height: 100%;
            background: #4A90E2;
            width: 0%;
            transition: width 0.3s ease;
        }
        
        .cr-progress-bar__message {
            font-size: 14px;
            margin-top: 8px;
            text-align: center;
        }
        
        @media (prefers-color-scheme: dark) {
            .cr-progress-bar__outline {
                background: #404040;
            }
            
            .cr-progress-bar__fill {
                background: #6BB6FF;
            }
        }
        
        /* ------------------------------------------------------------------ */
        /* Create Group Section: Top */
        
        .cr-create-group-section {
            margin-top: 20px;
            padding: 16px;
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            border-radius: 8px;
        }

        .cr-form-row {
            margin-bottom: 16px;
        }
        
        /* Remove bottom margin from checkbox row when checkbox is unchecked
         * the following #cr-create-group-form is hidden */
        .cr-form-row:has(input#cr-create-group-checkbox:not(:checked)) {
            margin-bottom: 0;
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
        
        @media (prefers-color-scheme: dark) {
            .cr-create-group-section {
                background: #2d3748;
                border-color: #4a5568;
            }
        }
        
        /* ------------------------------------------------------------------ */
        /* Create Group Section: Form */
        
        .cr-create-group-form {
            border-top: 1px solid #e9ecef;
            padding-top: 16px;
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
        
        @media (prefers-color-scheme: dark) {
            .cr-create-group-form {
                border-color: #4a5568;
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
        }
        
        /* ------------------------------------------------------------------ */
        /* Create Group Section: Form: Preview Members */
        
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
        /* Create Group Section: Form: Action Buttons */
        
        .cr-create-group-form__actions {
            margin-top: 16px;
            display: flex;
            align-items: center;
            gap: 12px;
            transition: margin-top 0.6s ease-out;
        }
        /* Remove top margin from form actions when collapsible content is collapsed */
        .slide-up + .cr-create-group-form__actions {
            margin-top: 0;
        }
        
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
        /* Animations */
        
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
            }
            to {
                opacity: 0;
                max-height: 0;
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
        
        <div class="cr-page__actions">
            <button onclick="history.back()" class="cr-button cr-button--secondary">
                ← Go Back
            </button>
            <button id="cr-download-url-button" {'disabled ' if readonly else ''}onclick="onDownloadUrlButtonClicked()" class="cr-button cr-button--primary">⬇ Download</button>
        </div>
        """
    ).strip()
    
    content_bottom_html = dedent(
        f"""
        <div id="cr-download-progress-bar" class="cr-download-progress-bar">
            <div class="cr-progress-bar__outline">
                <div id="cr-download-progress-bar__fill" class="cr-progress-bar__fill"></div>
            </div>
            <div id="cr-download-progress-bar__message" class="cr-progress-bar__message">Preparing download...</div>
        </div>
        
        <div class="cr-create-group-section">
            <div class="cr-form-row">
                <label class="cr-checkbox">
                    <input type="checkbox" id="cr-create-group-checkbox" {'disabled ' if readonly else ''}onchange="onCreateGroupCheckboxClicked()">
                    <span>Create Group for Similar Pages</span>
                </label>
            </div>
            
            <div id="cr-create-group-form" class="cr-create-group-form" style="display: none;">
                <div id="cr-create-group-form__collapsible-content">
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
                            <input type="checkbox" id="cr-download-immediately-checkbox" checked onchange="updateDownloadOrCreateGroupButtonTitleAndStyle()">
                            <span>Download Group Immediately</span>
                        </label>
                    </div>
                </div>
                
                <div class="cr-create-group-form__actions">
                    <button id="cr-cancel-group-button" class="cr-button cr-button--secondary" onclick="onCancelCreateGroupButtonClicked()">Cancel</button>
                    <button id="cr-group-action-button" class="cr-button cr-button--primary" onclick="onDownloadOrCreateGroupButtonClicked()">⬇ Download</button>
                    <span id="cr-group-action-message" class="cr-action-message"></span>
                </div>
            </div>
        </div>
        """
    ).strip()
    
    script_html = dedent(
        """
        <script>
            // NOTE: Patched by tests
            window.crReload = function() {
                window.location.reload();
            };
            
            // -----------------------------------------------------------------
            // Download URL Button
            
            // Used to receive download progress updates
            let eventSource = null;
            
            async function onDownloadUrlButtonClicked() {
                const createGroupCheckbox = document.getElementById('cr-create-group-checkbox');
                const groupShouldBeCreated = (
                    createGroupCheckbox.checked &&
                    isFormEnabled()  // form action not already performed
                );
                if (groupShouldBeCreated) {
                    const downloadImmediatelyCheckbox = document.getElementById('cr-download-immediately-checkbox');
                    if (downloadImmediatelyCheckbox.checked) {
                        // Press "Download" button in the group form
                        await onDownloadOrCreateGroupButtonClicked();
                        return;
                    } else {
                        // Press "Create" button in the group form,
                        // then download the individual URL if successful
                        await onDownloadOrCreateGroupButtonClicked(
                            /*downloadUrlImmediately=*/true);
                        return;
                    }
                } else {
                    const groupWasCreated = createGroupCheckbox.checked;
                    const rootUrlShouldBeCreated = !groupWasCreated;
                    await startUrlDownload(/*isRoot=*/rootUrlShouldBeCreated);
                }
            }
            
            async function startUrlDownload(isRoot) {
                const downloadButton = document.getElementById('cr-download-url-button');
                const progressDiv = document.getElementById('cr-download-progress-bar');
                const progressFill = document.getElementById('cr-download-progress-bar__fill');
                const progressText = document.getElementById('cr-download-progress-bar__message');
                
                // Disable the download button
                downloadButton.disabled = true;
                downloadButton.textContent = '⬇ Downloading...';
                
                // Show progress with animation
                progressDiv.style.display = 'block';
                // Force a reflow to ensure display: block is applied before adding the animation class
                progressDiv.offsetHeight;
                progressDiv.classList.add('show');
                progressFill.style.width = '0%%';
                progressText.textContent = 'Starting download...';
                
                try {
                    // Start the download
                    const downloadUrl = '/_/crystal/download-url';
                    const response = await fetch(downloadUrl, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({
                            url: %(archive_url_json)s,
                            is_root: isRoot,
                        })
                    });
                    if (!response.ok) {
                        const errorData = await response.json();
                        throw new Error(errorData.error || 'Failed to start download');
                    }
                    
                    const result = await response.json();
                    const taskId = result.task_id;
                    
                    // Listen for download progress updates
                    const progressUrl = `/_/crystal/download-progress?task_id=${encodeURIComponent(taskId)}`;
                    eventSource = new EventSource(progressUrl);
                    
                    eventSource.onmessage = function(event) {
                        const data = JSON.parse(event.data);
                        
                        if (data.error) {
                            // Update progress with error
                            progressFill.style.width = '0%%';
                            progressText.textContent = `Error: ${data.error}`;
                            
                            eventSource.close();
                            
                            // Enable the download button
                            downloadButton.disabled = false;
                            downloadButton.textContent = '⬇ Download';
                            
                            return;
                        }
                        
                        if (data.status === 'complete') {
                            // Update progress with success
                            progressFill.style.width = '100%%';
                            progressText.textContent = 'Download completed! Reloading page...';
                            
                            eventSource.close();
                            
                            // Reload the page ASAP
                            window.crReload();
                        } else if (data.status === 'in_progress') {
                            progressFill.style.width = `${data.progress}%%`;
                            progressText.textContent = data.message;
                        } else {
                            console.warn(`Unknown download status: ${data.status}`);
                        }
                    };
                    
                    eventSource.onerror = function(event) {
                        // Update progress with error
                        progressFill.style.width = '0%%';
                        progressText.textContent = 'Download failed.';
                        
                        eventSource.close();
                        
                        // Enable the download button
                        downloadButton.disabled = false;
                        downloadButton.textContent = '⬇ Download';
                    };
                } catch (error) {
                    console.error('Download error:', error);
                    
                    // Update progress with error
                    progressFill.style.width = '0%%';
                    progressText.textContent = `Download failed: ${error.message}`;
                    
                    if (eventSource) {
                        eventSource.close();
                    }
                    
                    // Enable the download button
                    downloadButton.disabled = false;
                    downloadButton.textContent = '⬇ Download';
                }
            }
            
            // Close event source when page unloads
            window.addEventListener('beforeunload', function() {
                if (eventSource) {
                    eventSource.close();
                }
            });
            
            // -----------------------------------------------------------------
            // Create Group Form: Show/Hide
            
            const createGroupFormData = %(create_group_form_data_json)s;
            
            function onCreateGroupCheckboxClicked() {
                // (Browser already toggled the checked state of the checkbox)
                updateCreateGroupFormVisible();
            }
            
            // Shows the Create Group Form iff the Create Group checkbox is ticked.
            function updateCreateGroupFormVisible() {
                const checkbox = document.getElementById('cr-create-group-checkbox');
                const form = document.getElementById('cr-create-group-form');
                
                if (checkbox.checked) {
                    form.style.display = 'block';
                    populateSourceDropdown();
                    updatePreviewUrls();
                    updateDownloadOrCreateGroupButtonTitleAndStyle();
                } else {
                    form.style.display = 'none';
                }
            }
            
            // Collapses the Create Group Form after a Create actions succeeded,
            // leaving the success message visible.
            function collapseCreateGroupForm() {
                const collapsibleContent = document.getElementById('cr-create-group-form__collapsible-content');
                collapsibleContent.classList.add('slide-up');
            }
            
            // -----------------------------------------------------------------
            // Create Group Form: Fields
            
            // Respond to Enter/Escape keys
            document.addEventListener('DOMContentLoaded', function() {
                const urlPatternInput = document.getElementById('cr-group-url-pattern');
                urlPatternInput.addEventListener('keydown', handleFormKeydown);
                
                const nameInput = document.getElementById('cr-group-name');
                nameInput.addEventListener('keydown', handleFormKeydown);
            });
            
            function handleFormKeydown(event) {
                if (event.key === 'Enter') {
                    // Trigger the primary button, which is always a Download button
                    onDownloadUrlButtonClicked();
                    
                    event.preventDefault();
                } else if (event.key === 'Escape') {
                    // Trigger the cancel button
                    onCancelCreateGroupButtonClicked();
                    
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
            // Create Group Form: Cancel Button
            
            function onCancelCreateGroupButtonClicked() {
                const checkbox = document.getElementById('cr-create-group-checkbox');
                checkbox.checked = false;
                updateCreateGroupFormVisible();
            }
            
            // -----------------------------------------------------------------
            // Create Group Form: Download/Create Group Button
            
            // Initialize Download/Create button on page load
            document.addEventListener('DOMContentLoaded', function() {
                updateDownloadOrCreateGroupButtonTitleAndStyle();
            });
            
            // Updates the Download/Create button at the bottom of the
            // Create Group Form to display the appropriate title,
            // depending on whether the Download Immediately checkbox is ticked.
            function updateDownloadOrCreateGroupButtonTitleAndStyle() {
                const downloadImmediatelyCheckbox = document.getElementById('cr-download-immediately-checkbox');
                const actionButton = document.getElementById('cr-group-action-button');
                
                if (downloadImmediatelyCheckbox && downloadImmediatelyCheckbox.checked) {
                    actionButton.textContent = '⬇ Download';
                    actionButton.className = 'cr-button cr-button--primary';
                } else {
                    actionButton.textContent = '✚ Create';
                    actionButton.className = 'cr-button cr-button--secondary';
                }
            }
            
            async function onDownloadOrCreateGroupButtonClicked(downloadUrlImmediately/*=false*/) {
                const urlPattern = document.getElementById('cr-group-url-pattern').value.trim();
                const sourceValue = document.getElementById('cr-group-source').value;
                const name = document.getElementById('cr-group-name').value.trim();
                const downloadGroupImmediately = document.getElementById('cr-download-immediately-checkbox').checked;
                
                if (!urlPattern) {
                    showActionMessage('✖️ Please enter a URL pattern.', /*isSuccess=*/false);
                    return;
                }
                
                clearActionMessage();
                setFormEnabled(false);
                
                const actionButton = document.getElementById('cr-group-action-button');
                const originalText = actionButton.textContent;
                actionButton.textContent = downloadGroupImmediately ? 'Creating & Starting Download...' : 'Creating...';
                
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
                    showActionMessage('✅ Group created successfully!', /*isSuccess=*/true);
                    
                    // If download was requested, start individual URL download
                    // otherwise collapse the disabled form to show only essential elements
                    if (downloadGroupImmediately || downloadUrlImmediately) {
                        await startUrlDownload(/*isRoot=*/false);
                    } else {
                        collapseCreateGroupForm();
                    }
                } catch (error) {
                    console.error('Group action error:', error);
                    showActionMessage('✖️ Failed to create group', /*isSuccess=*/false);
                    setFormEnabled(true);
                } finally {
                    actionButton.textContent = originalText;
                }
            }
            
            // -----------------------------------------------------------------
            // Create Group Form: Action Message
            
            function showActionMessage(message, isSuccess) {
                const messageElement = document.getElementById('cr-group-action-message');
                messageElement.textContent = message;
                messageElement.className = `cr-action-message ${isSuccess ? 'success' : 'error'}`;
            }
            
            function clearActionMessage() {
                const messageElement = document.getElementById('cr-group-action-message');
                messageElement.textContent = '';
                messageElement.className = 'cr-action-message';
            }
            
            // -----------------------------------------------------------------
            // Create Group Form: Enabled State
            
            function setFormEnabled(enabled) {
                const inputs = document.querySelectorAll('#cr-create-group-form input, #cr-create-group-form select, #cr-create-group-form button');
                inputs.forEach(input => {
                    input.disabled = !enabled;
                });
                
                const createGroupCheckbox = document.getElementById('cr-create-group-checkbox');
                createGroupCheckbox.disabled = !enabled;
            }
            
            function isFormEnabled() {
                const createGroupCheckbox = document.getElementById('cr-create-group-checkbox');
                return !createGroupCheckbox.disabled;
            }
            
            // -----------------------------------------------------------------
        </script>
        """ % {
            'archive_url_json': archive_url_json,
            'create_group_form_data_json': json.dumps(create_group_form_data)
        }
    ).strip()
    
    return _base_page_html(
        title_html='Not in Archive | Crystal',
        style_html=(_URL_BOX_STYLE_TEMPLATE + '\n' + not_in_archive_styles),
        content_html=(content_top_html + content_bottom_html),
        script_html=script_html,
    )


def fetch_error_html(
        *, archive_url: str,
        error_type_html: str,
        error_message_html: str,
        ) -> str:    
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
        </div>
        """
    ).strip()
    
    return _base_page_html(
        title_html='Fetch Error | Crystal',
        style_html=(
            _URL_BOX_STYLE_TEMPLATE
        ),
        content_html=content_html,
        script_html='',
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
        margin: 30px 0;
    }
    .cr-page__actions:last-child {
        margin-bottom: 0;
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

_URL_BOX_STYLE_TEMPLATE = dedent(
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