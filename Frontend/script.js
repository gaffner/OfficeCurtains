const ACCESS_DENIED_MESSAGE = 'Access denied: your network provider is not allowed to use this service.';

/**
 * Read a response body defensively. The server can legitimately answer with
 * HTML (blocked page, proxy error page), so never assume the body is JSON.
 */
async function readPayload(response) {
    const contentType = (response.headers.get('content-type') || '').toLowerCase();
    if (!contentType.includes('application/json')) {
        return { isJson: false, data: null };
    }
    try {
        return { isJson: true, data: await response.json() };
    } catch (err) {
        return { isJson: false, data: null };
    }
}

/** Turn any non-OK / non-JSON response into a message a human can act on. */
function describeFailure(response, payload, fallback) {
    if (payload.isJson && payload.data && typeof payload.data.detail === 'string') {
        return payload.data.detail;
    }
    if (response.redirected && response.url.includes('blocked.html')) {
        return ACCESS_DENIED_MESSAGE;
    }
    if (response.status === 401 || response.status === 403) {
        return ACCESS_DENIED_MESSAGE;
    }
    if (response.status === 429) {
        return 'Too many requests - please wait a moment and try again.';
    }
    if (response.status >= 500) {
        return `The server is having trouble (error ${response.status}). Please try again shortly.`;
    }
    if (!payload.isJson) {
        return ACCESS_DENIED_MESSAGE;
    }
    return fallback;
}

/**
 * Perform a request and always resolve to { ok, data, message }.
 * Network failures and non-JSON bodies produce an indicative message
 * rather than an opaque JSON parse error.
 */
async function requestJson(url, options = {}) {
    let response;
    try {
        response = await fetch(url, {
            credentials: 'include',
            ...options,
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
                ...(options.headers || {})
            }
        });
    } catch (err) {
        return {
            ok: false,
            data: null,
            message: 'Cannot reach the server. Please check your connection and try again.'
        };
    }

    const payload = await readPayload(response);

    if (!response.ok || !payload.isJson) {
        return {
            ok: false,
            status: response.status,
            data: payload.data,
            message: describeFailure(response, payload, `Request failed (error ${response.status}).`)
        };
    }

    return { ok: true, status: response.status, data: payload.data, message: null };
}

class CurtainControl {
    constructor() {
        this.favorites = [];
        this.roomDirections = {};
        this.roomNicknames = {};
        this.roomInput = null;
        this.errorDiv = null;
        this.statusDiv = null;
        this.roomsList = null;
        this.emptyState = null;

        this.addRoom = this.addRoom.bind(this);
        this.removeRoom = this.removeRoom.bind(this);
        this.moveCurtain = this.moveCurtain.bind(this);
        this.handleDirectionChange = this.handleDirectionChange.bind(this);
        this.setNickname = this.setNickname.bind(this);

        document.addEventListener('DOMContentLoaded', () => this.init());
    }

    init() {
        this.roomInput = document.getElementById('roomInput');
        this.errorDiv = document.getElementById('error');
        this.statusDiv = document.getElementById('status');
        this.roomsList = document.getElementById('roomsList');
        this.emptyState = document.getElementById('emptyState');
        this.tshirtCampaign = document.getElementById('tshirtCampaign');

        const savedData = JSON.parse(localStorage.getItem('curtainData')) || {};
        this.favorites = savedData.favorites || [];
        this.roomDirections = savedData.roomDirections || {};
        this.roomNicknames = savedData.roomNicknames || {};

        this.roomInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.addRoom();
        });

        this.renderRooms();
    }

    saveToLocalStorage() {
        const dataToSave = {
            favorites: this.favorites,
            roomDirections: this.roomDirections,
            roomNicknames: this.roomNicknames
        };
        localStorage.setItem('curtainData', JSON.stringify(dataToSave));
    }

    handleDirectionChange(room) {
        const select = document.querySelector(`#direction-${room}`);
        if (select) {
            this.roomDirections[room].selected = select.value;
            this.saveToLocalStorage();
        }
    }
    toggleReportForm() {
    const form = document.getElementById('reportForm');
    const button = document.getElementById('reportButton');
    if (form.style.display === 'none' || form.style.display === '') {
        form.style.display = 'block';
        button.textContent = 'Hide Report Form';
    } else {
        form.style.display = 'none';
        button.textContent = 'Report Problem';
    }
}

    submitReport() {
        const reportText = document.getElementById('reportText').value;
        if (!reportText.trim()) {
            document.getElementById('errorMessage').style.display = 'block';
            document.getElementById('successMessage').style.display = 'none';
            return;
        }

        const encodedReport = encodeURIComponent(reportText);

        requestJson(`/submit-report/${encodedReport}`, { method: 'GET' })
        .then(result => {
            if (result.ok) {
                document.getElementById('successMessage').style.display = 'block';
                document.getElementById('errorMessage').style.display = 'none';
                document.getElementById('reportText').value = '';
                setTimeout(() => {
                    document.getElementById('reportForm').style.display = 'none';
                    document.getElementById('successMessage').style.display = 'none';
                    document.getElementById('reportButton').textContent = 'Report Problem';
                }, 3000);
                return;
            }

            const errorBox = document.getElementById('errorMessage');
            errorBox.textContent = result.message;
            errorBox.style.display = 'block';
            document.getElementById('successMessage').style.display = 'none';
        });
    }
    async moveCurtain(room, direction) {
        const selectedDirection = this.roomDirections[room].selected;
        const url = selectedDirection ?
            `/control/${encodeURIComponent(room)}/${direction}?direction=${encodeURIComponent(selectedDirection)}` :
            `/control/${encodeURIComponent(room)}/${direction}`;

        if (direction === "stop")
            this.showStatus(`Curtain is stopping...`);
        else if (direction === "up")
            this.showStatus(`Curtain is going up`);
        else
            this.showStatus(`Curtain is going down`);

        const result = await requestJson(url, { method: 'GET' });

        if (!result.ok) {
            this.showError(`Could not ${direction} curtain in ${room}: ${result.message}`);
        }
    }

    addRoom() {
        const room = this.roomInput.value.trim().toUpperCase();

        if (!this.isValidRoomNumber(room)) {
            this.showError('Please enter a valid room number (e.g., 4B210)');
            return;
        }

        if (this.favorites.includes(room)) {
            this.showError('This room is already in your favorites');
            return;
        }

        requestJson(`/register/${encodeURIComponent(room)}`).then(result => {
            if (!result.ok) {
                if (result.status === 404) {
                    this.showError(`Room ${room} was not found.`);
                } else {
                    this.showError(result.message);
                }
                return;
            }

            const data = result.data;
            if (!Array.isArray(data) || data.length === 0) {
                this.showError(`Room ${room} returned no curtain directions.`);
                return;
            }

            this.favorites.push(room);
            this.roomDirections[room] = {
                directions: data,
                selected: data.length > 1 ? data[0] : null
            };
            this.saveToLocalStorage();
            this.roomInput.value = '';
            this.renderRooms();
        });
    }

    removeRoom(room) {
        this.favorites = this.favorites.filter(r => r !== room);
        delete this.roomDirections[room];
        delete this.roomNicknames[room];
        this.saveToLocalStorage();
        this.renderRooms();
    }

    setNickname(room, nickname) {
        if (nickname.trim()) {
            this.roomNicknames[room] = nickname.trim();
        } else {
            delete this.roomNicknames[room];
        }
        this.saveToLocalStorage();
    }

    renderRooms() {
        this.roomsList.innerHTML = '';
        this.emptyState.style.display = this.favorites.length ? 'none' : 'block';

        this.favorites.forEach(room => {
            const directions = this.roomDirections[room]?.directions || [];
            const selected = this.roomDirections[room]?.selected;
            const nickname = this.roomNicknames[room] || '';

            const directionDropdown = directions.length > 1 ? `
                <select id="direction-${room}" class="room-directions" onchange="curtainControl.handleDirectionChange('${room}')">
                    ${directions.map(dir => `
                        <option value="${dir}" ${dir === selected ? 'selected' : ''}>
                            ${dir}
                        </option>
                    `).join('')}
                </select>
            ` : '';

            const card = document.createElement('div');
            card.className = 'room-card';
            card.innerHTML = `
                <div class="room-info">
                    <span class="room-number">${room}</span>
                    <input 
                        type="search" 
                        class="room-nickname" 
                        placeholder="Add nickname..."
                        value="${nickname}"
                        id="nickname-${room}"
                        onblur="curtainControl.setNickname('${room}', this.value)"
                        onkeypress="if(event.key === 'Enter') this.blur()"
                    />
                </div>
                <div class="room-controls">
                    ${directionDropdown}
                    <button class="control-button btn-up" onclick="curtainControl.moveCurtain('${room}', 'up')">☝️</button>
                    <button class="control-button btn-down" onclick="curtainControl.moveCurtain('${room}', 'down')">👇</button>
                    <button class="control-button btn-stop" onclick="curtainControl.moveCurtain('${room}', 'stop')">✋</button>
                    <button class="control-button btn-remove" onclick="curtainControl.removeRoom('${room}')">×</button>
                </div>
            `;
            this.roomsList.appendChild(card);
        });
    }

    isValidRoomNumber(room) {
        console.log(room)
    return /^\d[A-Za-z][A-Za-z0-9]{3}$/.test(room);
    }


    showError(message) {
        this.errorDiv.textContent = message;
        this.errorDiv.style.display = 'block';
        // this.disableTshirtCampaign();
        setTimeout(() => {
            this.errorDiv.style.display = 'none';
            // this.enableTshirtCampaign();
        }, 3000);
    }

    showStatus(message) {
        this.statusDiv.textContent = message;
        this.statusDiv.style.display = 'block';
        // this.disableTshirtCampaign();
        setTimeout(() => {
            this.statusDiv.style.display = 'none';
            // this.enableTshirtCampaign();
        }, 5000);
    }

    disableTshirtCampaign() {
        this.tshirtCampaign.onclick = a => {};
        this.tshirtCampaign.style.cursor = "auto";
    }

    enableTshirtCampaign() {
        this.tshirtCampaign.onclick = a => {window.location.href='/Frontend/tshirt.html'};
        this.tshirtCampaign.style.cursor = "pointer";
    }
}

const curtainControl = new CurtainControl();
