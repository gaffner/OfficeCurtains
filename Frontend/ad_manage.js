// Ad management wizard: banner -> queue slot -> live campaign.

if (localStorage.getItem('dark-mode') === 'true') {
    document.body.classList.add('dark-mode');
}

const state = {
    campaign: null,
    config: null,
    queue: null,
};

const el = (id) => document.getElementById(id);

function showStep(n) {
    [1, 2, 3].forEach((i) => {
        el('panel-' + i).hidden = (i !== n);
    });
    document.querySelectorAll('.step').forEach((step) => {
        const num = Number(step.dataset.step);
        step.classList.toggle('current', num === n);
        step.classList.toggle('done', num < n);
    });
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function showError(box, message) {
    box.textContent = message;
    box.hidden = false;
}

function clearError(box) {
    box.textContent = '';
    box.hidden = true;
}

// The server always answers with JSON, but a proxy error or a dropped
// connection still has to produce something readable rather than a raw
// "Unexpected token '<'".
async function readError(response) {
    let detail;
    try {
        const body = await response.json();
        detail = body.detail;
    } catch (e) {
        detail = null;
    }

    if (Array.isArray(detail)) {
        detail = detail.map((d) => d.msg).join(', ');
    }
    if (detail) {
        return detail;
    }
    if (response.status === 403) {
        return 'Ads can only be set up from an allowed office network.';
    }
    if (response.status === 413) {
        return 'That image is too large to upload.';
    }
    return 'Something went wrong (error ' + response.status + '). Please try again.';
}

function plural(n, word) {
    return n + ' ' + word + (n === 1 ? '' : 's');
}

function formatDate(iso) {
    if (!iso) {
        return '\u2014';
    }
    const date = new Date(iso);
    if (isNaN(date)) {
        return iso;
    }
    return date.toLocaleString(undefined, {
        weekday: 'long', month: 'long', day: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });
}

// ---------------------------------------------------------------- config

async function loadConfig() {
    try {
        const response = await fetch('/api/ads/config');
        if (!response.ok) {
            return;
        }
        state.config = await response.json();
    } catch (e) {
        return;
    }

    const c = state.config;
    el('recSize').textContent = c.recommended_width + ' \u00d7 ' + c.recommended_height;
    el('formatHint').textContent =
        c.allowed_formats.join(', ') + ', up to ' + c.max_upload_mb + ' MB.';
    el('maxHoursHint').textContent = c.max_hours;
    hoursInput.max = c.max_hours;
    if (Number(hoursInput.value) > c.max_hours) {
        hoursInput.value = c.max_hours;
    }
    updateHoursLabel();

    if (c.support_whatsapp) {
        const link = 'https://wa.me/' + c.support_whatsapp;
        el('waLink').href = link;
        el('startWaLink').href = link;
    }

    // Uploading is free, so the code step never runs: drop it from the
    // progress list rather than showing a step that is always skipped.
    if (!c.require_code) {
        const codeStep = document.querySelector('.step[data-step="2"]');
        if (codeStep) {
            codeStep.remove();
        }
        const lastNum = document.querySelector('.step[data-step="3"] .step-num');
        if (lastNum) {
            lastNum.textContent = '2';
        }
    }
}

async function loadQueueHint() {
    let queue;
    try {
        const response = await fetch('/api/ads/queue');
        if (!response.ok) {
            return;
        }
        queue = await response.json();
    } catch (e) {
        return;
    }

    state.queue = queue;
    const hint = el('queueHint');

    if (!queue.current) {
        hint.textContent = 'The slot is free right now, so your ad starts as soon as you upload it.';
    } else {
        const waiting = queue.upcoming.length;
        hint.textContent = 'One ad is on air'
            + (waiting ? ' and ' + plural(waiting, 'other') + ' waiting' : '')
            + '. Yours starts ' + formatDate(queue.free_from) + '.';
    }
    hint.hidden = false;
}

// ---------------------------------------------------------------- step 1

const hoursInput = el('hours');

function updateHoursLabel() {
    el('hoursValue').textContent = plural(Number(hoursInput.value), 'hour');
}

hoursInput.addEventListener('input', updateHoursLabel);
updateHoursLabel();

el('banner').addEventListener('change', (event) => {
    const file = event.target.files && event.target.files[0];
    const image = el('previewImage');
    const empty = document.querySelector('.preview-empty');

    if (!file) {
        image.hidden = true;
        empty.hidden = false;
        return;
    }

    image.src = URL.createObjectURL(file);
    image.hidden = false;
    empty.hidden = true;
});

el('adForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const errorBox = el('formError');
    clearError(errorBox);

    const file = el('banner').files[0];
    if (!file) {
        showError(errorBox, 'Please choose a banner image.');
        return;
    }
    if (!el('targetUrl').value.trim()) {
        showError(errorBox, 'Please add the link the banner should open.');
        return;
    }

    const form = new FormData();
    form.append('banner', file);
    form.append('target_url', el('targetUrl').value.trim());
    form.append('hours', hoursInput.value);

    const button = el('submitBtn');
    button.disabled = true;
    button.textContent = 'Uploading\u2026';

    try {
        const response = await fetch('/api/ads/draft', { method: 'POST', body: form });
        if (!response.ok) {
            showError(errorBox, await readError(response));
            return;
        }
        state.campaign = await response.json();

        if (state.campaign.status === 'active') {
            renderCampaign();
            showStep(3);
        } else {
            renderOrder();
            showStep(2);
        }
    } catch (e) {
        showError(errorBox, 'Could not reach the server. Please check your connection.');
    } finally {
        button.disabled = false;
        button.textContent = 'Next \u2192';
    }
});

el('backTo1').addEventListener('click', () => showStep(1));

// ---------------------------------------------------------------- step 2

function renderOrder() {
    el('orderLine').textContent = plural(state.campaign.hours, 'hour') + ' on air';
}

el('code').addEventListener('input', () => clearError(el('codeError')));

el('codeBtn').addEventListener('click', async () => {
    const errorBox = el('codeError');
    clearError(errorBox);

    const code = el('code').value.trim();
    if (!code) {
        showError(errorBox, 'Please enter your confirmation code.');
        return;
    }

    const button = el('codeBtn');
    button.disabled = true;
    button.textContent = 'Checking\u2026';

    try {
        const response = await fetch('/api/ads/' + encodeURIComponent(state.campaign.id) + '/redeem', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code: code }),
        });

        if (!response.ok) {
            showError(errorBox, await readError(response));
            return;
        }

        state.campaign = await response.json();
        renderCampaign();
        showStep(3);
    } catch (e) {
        showError(errorBox, 'Could not reach the server. Please check your connection.');
    } finally {
        button.disabled = false;
        button.textContent = 'Activate campaign';
    }
});

// ---------------------------------------------------------------- step 3

function renderCampaign() {
    const c = state.campaign;

    el('sumDuration').textContent = plural(c.hours, 'hour') + ' on air';

    const startsAt = new Date(c.starts_at);
    const onAirNow = !isNaN(startsAt) && startsAt <= new Date();
    el('successBadge').textContent = onAirNow
        ? '\u2713 Your campaign is live'
        : '\u2713 Your campaign is booked';
    el('sumPosition').textContent = onAirNow
        ? 'On air now'
        : 'Queued \u2014 starts after the ads already booked';
    el('sumStart').textContent = formatDate(c.starts_at);
    el('sumEnd').textContent = formatDate(c.ends_at);

    const link = el('sumLink');
    link.textContent = '';
    const anchor = document.createElement('a');
    anchor.href = c.target_url;
    anchor.target = '_blank';
    anchor.rel = 'noopener';
    anchor.textContent = c.target_url;
    link.appendChild(anchor);

    el('liveImage').src = c.banner_url;

    if (c.support_whatsapp) {
        el('waLink').href = 'https://wa.me/' + c.support_whatsapp;
    }
}

loadConfig();
loadQueueHint();
