/**
 * Master Kobo Form & Navigation Loader
 * Handles frame-busting, form embedding, and email persistence across pages.
 */

// --- 1. GLOBAL FRAME BUSTER ---
// Ensures no page ever gets stuck inside an iframe
if (window.self !== window.top) {
    window.top.location.href = window.location.href;
}

// --- HELPER: Get Email Safely ---
function getEmailFromUrl() {
    const urlParams = new URLSearchParams(window.location.search);
    const email = urlParams.get("email");
    // Return empty string if null, so we don't print "null" in the form
    return email ? email : ""; 
}

// --- HELPER: Build Next Page URL ---
function buildNextUrl(path, email) {
    // Resolve the relative path (../next/) to a full absolute URL
    const baseUrl = new URL(path, window.location.href);
    if (email) {
        baseUrl.searchParams.set("email", email);
    }
    return baseUrl.href;
}

/**
 * FUNCTION 1: Load Kobo Form
 * Usage: loadKoboForm('div-id', 'koboid', '../next/', '650px');
 */
function loadKoboForm(containerId, koboId, nextPagePath, height = '650px', width = '100%') {
    const container = document.getElementById(containerId);
    if (!container) return;

    const email = getEmailFromUrl();
    const absoluteReturnUrl = buildNextUrl(nextPagePath, email);

    // Construct URL parameters
    let koboUrl = `https://ee.kobotoolbox.org/single/${koboId}?hide=saving&return_url=${encodeURIComponent(absoluteReturnUrl)}`;
    
    // Only append email pre-fill if we actually have one
    if (email) {
        koboUrl += `&d[email]=${encodeURIComponent(email)}`;
    }

    // Render Iframe
    container.innerHTML = `
        <iframe 
            src="${koboUrl}" 
            style="width: ${width}; 
                   max-width: 500px; 
                   height: ${height}; 
                   border: 1px solid #ccc; 
                   border-radius: 8px; 
                   box-shadow: 0 4px 10px rgba(0,0,0,0.1); 
                   display: block; margin: 0 auto; overflow: hidden;"
        ></iframe>`;
}

/**
 * FUNCTION 2: Load Navigation Button (For pages without forms)
 * Usage: loadNavigationButton('div-id', '../next/', 'Click to Continue');
 */
function loadNavigationButton(containerId, nextPagePath, buttonLabel = "Continue to Next Section") {
    const container = document.getElementById(containerId);
    if (!container) return;

    const email = getEmailFromUrl();

    // Render Button
    container.innerHTML = `
        <div style="text-align: center; margin-top: 30px;">
            <button id="nav-btn-${containerId}" 
                style="padding: 15px 30px; font-size: 18px; 
                       background-color: #007bff; color: white; border: none; 
                       border-radius: 8px; cursor: pointer; transition: background 0.2s;">
                ${buttonLabel}
            </button>
        </div>`;

    // Add Click Handler
    document.getElementById(`nav-btn-${containerId}`).addEventListener("click", function() {
        // Navigate to the next page using the helper to attach email
        window.location.href = buildNextUrl(nextPagePath, email);
    });
}
