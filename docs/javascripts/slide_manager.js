/**
 * slide-manager.js
 */

// --- 1. GLOBAL FRAME BUSTER ---
if (window.self !== window.top) {
    window.top.location.href = window.location.href;
}

// --- 2. AGGRESSIVE SCROLL LOCK ---
// We "lock" the scroll to the top immediately to prevent the Kobo jump.
const lockScroll = () => {
    window.scrollTo(0, 0);
};
window.addEventListener('scroll', lockScroll);

// Safety: Re-enable scrolling after 3 seconds even if something fails
setTimeout(() => {
    window.removeEventListener('scroll', lockScroll);
}, 3000);

document.addEventListener('DOMContentLoaded', () => {
    const config = document.getElementById('slide-config');
    if (!config) {
        window.removeEventListener('scroll', lockScroll);
        return;
    }

    // --- SMART PATH FIXER ---
    const getResolvedNextUrl = (rawUrl) => {
        if (!rawUrl) return '';
        if (!rawUrl.startsWith('../')) return rawUrl;
        const isDirRoot = window.location.pathname.endsWith('/');
        const pathSegments = window.location.pathname.split('/').filter(p => p && !p.includes('.html'));
        const isGitHub = window.location.hostname.includes('github.io');
        const isHome = (isGitHub && pathSegments.length === 1) || (!isGitHub && pathSegments.length === 0);
        if (isDirRoot && isHome) {
            return rawUrl.replace(/^\.\.\//, './');
        }
        return rawUrl;
    };

    const type = config.dataset.type;
    const nextUrl = getResolvedNextUrl(config.dataset.next);
    const imgSource = config.dataset.img;
    const koboId = config.dataset.koboId; 
    const koboWidth = config.dataset.width || '100%'; 
    
    const container = document.createElement('div');
    container.id = 'dynamic-slide-content';
    config.parentNode.insertBefore(container, config.nextSibling);

    const getEmail = () => {
        const urlParams = new URLSearchParams(window.location.search);
        if (urlParams.has('email')) {
            const email = urlParams.get('email');
            sessionStorage.setItem('participant_email', email);
            return email;
        }
        return sessionStorage.getItem('participant_email') || '';
    };

    const saveEmail = (email) => {
        sessionStorage.setItem('participant_email', email);
    };

    const goToNext = (url) => {
        if (!url) return;
        const currentEmail = getEmail();
        let targetUrl = url;
        if (currentEmail) {
            const separator = url.includes('?') ? '&' : '?';
            targetUrl = `${url}${separator}email=${encodeURIComponent(currentEmail)}`;
        }
        if (window.top !== window.self) {
            window.top.location.href = targetUrl;
        } else {
            window.location.href = targetUrl;
        }
    };

    // --- TYPE SPECIFIC LOGIC ---

    if (type === 'start') {
        window.removeEventListener('scroll', lockScroll); // No iframe here, unlock early
        const existingEmail = getEmail();
        container.innerHTML = `
            <div class="input-group">
                <input type="email" id="user-email" placeholder="Enter your email (optional)" value="${existingEmail}" />
                <button id="start-btn" class="nav-btn">Start Session</button>
            </div>
        `;
        const startBtn = document.getElementById('start-btn');
        if (startBtn) {
            startBtn.addEventListener('click', () => {
                saveEmail(document.getElementById('user-email').value);
                goToNext(nextUrl); 
            });
        }
    }

    else if (type === 'kobo') {
        const email = getEmail();
        const nextAbsoluteUrl = new URL(nextUrl, window.location.href);
        if (email) nextAbsoluteUrl.searchParams.set("email", email);

        let finalKoboUrl = `https://ee.kobotoolbox.org/single/${koboId}?hide=saving&return_url=${encodeURIComponent(nextAbsoluteUrl.href)}`;
        if (email) finalKoboUrl += `&d[email]=${encodeURIComponent(email)}`;

        container.innerHTML = `
            <div class="iframe-wrapper">
                <iframe 
                    id="kobo-iframe"
                    src="${finalKoboUrl}" 
                    width="${koboWidth}" 
                    height="650px" 
                    frameborder="0" 
                    style="width: ${koboWidth};">
                </iframe>
            </div>
            <div class="nav-wrapper">
                <p><em>Form not loading or redirecting?</em></p>
                <button id="next-btn" class="nav-btn">Manually Go Next</button>
            </div>
        `;

        const iframe = document.getElementById('kobo-iframe');
        iframe.onload = () => {
            // Once the iframe loads, wait a tiny beat for the autofocus to finish, 
            // then unlock the scroll and force the top position.
            setTimeout(() => {
                window.removeEventListener('scroll', lockScroll);
                window.scrollTo(0, 0);
            }, 500);
        };

        document.getElementById('next-btn').addEventListener('click', () => goToNext(nextUrl));
    }

    else {
        // For 'figure' and 'simple' types, unlock immediately
        window.removeEventListener('scroll', lockScroll);
        
        if (type === 'figure') {
            const timestamp = new Date().getTime();
            const freshImgSrc = `${imgSource}${imgSource.includes('?') ? '&' : '?'}v=${timestamp}`;
            container.innerHTML = `
                <div class="figure-wrapper"><img src="${freshImgSrc}" class="slide-figure" /></div>
                <div class="nav-wrapper"><button id="next-btn" class="nav-btn">Next Slide</button></div>
            `;
            document.getElementById('next-btn').addEventListener('click', () => goToNext(nextUrl));
        }
        else if (type === 'simple') {
            container.innerHTML = `<div class="nav-wrapper"><button id="next-btn" class="nav-btn">Next Slide</button></div>`;
            document.getElementById('next-btn').addEventListener('click', () => goToNext(nextUrl));
        }
    }
});
