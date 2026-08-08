/**
 * Ads queue page: shows the banner on air now and the ones booked behind it.
 *
 * The queue is public and anonymous, so nothing here identifies an advertiser
 * beyond the banner they uploaded and the link it points at.
 */

if (localStorage.getItem('dark-mode') === 'true') {
    document.body.classList.add('dark-mode');
}

function el(id) {
    return document.getElementById(id);
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
        weekday: 'short', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });
}

function remaining(endsAt, now) {
    const end = new Date(endsAt);
    if (isNaN(end)) {
        return '';
    }
    const minutes = Math.max(0, Math.round((end - now) / 60000));
    if (minutes < 60) {
        return plural(minutes, 'minute') + ' left';
    }
    const hours = Math.floor(minutes / 60);
    const rest = minutes % 60;
    return plural(hours, 'hour') + (rest ? ' ' + rest + ' min' : '') + ' left';
}

function buildSlot(slot, options) {
    const card = document.createElement('article');
    card.className = 'slot ' + options.className;

    const badge = document.createElement('span');
    badge.className = 'slot-badge';
    badge.textContent = options.badge;
    card.appendChild(badge);

    const frame = document.createElement('div');
    frame.className = 'slot-banner';

    const image = document.createElement('img');
    image.src = slot.banner_url;
    image.alt = 'Advertisement banner';
    image.loading = 'lazy';
    frame.appendChild(image);
    card.appendChild(frame);

    const meta = document.createElement('dl');
    meta.className = 'slot-meta';

    options.rows.forEach((row) => {
        const term = document.createElement('dt');
        term.textContent = row[0];
        const value = document.createElement('dd');
        value.textContent = row[1];
        meta.appendChild(term);
        meta.appendChild(value);
    });

    card.appendChild(meta);
    return card;
}

function buildConnector() {
    const arrow = document.createElement('div');
    arrow.className = 'connector';
    arrow.setAttribute('aria-hidden', 'true');
    arrow.textContent = '\u2193';
    return arrow;
}

function buildEmptySlot(message) {
    const card = document.createElement('article');
    card.className = 'slot empty';
    const text = document.createElement('p');
    text.textContent = message;
    card.appendChild(text);
    return card;
}

function render(queue) {
    const now = new Date(queue.now);
    const pipeline = el('pipeline');
    pipeline.textContent = '';

    if (queue.current) {
        pipeline.appendChild(buildSlot(queue.current, {
            className: 'current',
            badge: 'On air now',
            rows: [
                ['Runs for', plural(queue.current.hours, 'hour')],
                ['Ends', formatDate(queue.current.ends_at)],
                ['Time left', remaining(queue.current.ends_at, now)],
            ],
        }));
    } else {
        pipeline.appendChild(buildEmptySlot(
            'No ad is on air at the moment. The slot is free \u2014 yours could be next.'
        ));
    }

    queue.upcoming.forEach((slot, index) => {
        pipeline.appendChild(buildConnector());
        pipeline.appendChild(buildSlot(slot, {
            className: 'upcoming',
            badge: index === 0 ? 'Up next' : 'Queued \u00b7 #' + (index + 1),
            rows: [
                ['Runs for', plural(slot.hours, 'hour')],
                ['Starts', formatDate(slot.starts_at)],
                ['Ends', formatDate(slot.ends_at)],
            ],
        }));
    });

    if (queue.current && !queue.upcoming.length) {
        pipeline.appendChild(buildConnector());
        pipeline.appendChild(buildEmptySlot(
            'Nothing booked after this one. The next slot is yours for the taking.'
        ));
    }

    el('freeFromHint').textContent = queue.current
        ? 'Next free slot: ' + formatDate(queue.free_from)
            + ' \u00b7 up to ' + plural(queue.max_hours, 'hour') + ' per campaign, free.'
        : 'Up to ' + plural(queue.max_hours, 'hour') + ' per campaign, free.';

    el('loading').hidden = true;
    pipeline.hidden = false;
}

async function loadQueue() {
    try {
        const response = await fetch('/api/ads/queue');
        if (!response.ok) {
            throw new Error('bad status');
        }
        render(await response.json());
    } catch (e) {
        el('loading').hidden = true;
        const box = el('queueError');
        box.textContent = 'Could not load the ad queue. Please try again in a moment.';
        box.hidden = false;
    }
}

loadQueue();
setInterval(loadQueue, 60000);
