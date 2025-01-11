class CurtainControl {
    constructor() {
        this.favorites = [];
        this.roomDirections = {};
        this.roomInput = null;
        this.errorDiv = null;
        this.statusDiv = null;
        this.roomsList = null;
        this.emptyState = null;

        this.addRoom = this.addRoom.bind(this);
        this.removeRoom = this.removeRoom.bind(this);
        this.moveCurtain = this.moveCurtain.bind(this);
        this.handleDirectionChange = this.handleDirectionChange.bind(this);

        document.addEventListener('DOMContentLoaded', () => this.init());
    }

    init() {
        this.roomInput = document.getElementById('roomInput');
        this.errorDiv = document.getElementById('error');
        this.statusDiv = document.getElementById('status');
        this.roomsList = document.getElementById('roomsList');
        this.emptyState = document.getElementById('emptyState');

        const savedData = JSON.parse(localStorage.getItem('curtainData')) || {};
        this.favorites = savedData.favorites || [];
        this.roomDirections = savedData.roomDirections || {};

        this.roomInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.addRoom();
        });

        this.renderRooms();
    }

    saveToLocalStorage() {
        const dataToSave = {
            favorites: this.favorites,
            roomDirections: this.roomDirections
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

    async moveCurtain(room, direction) {
        try {
            const selectedDirection = this.roomDirections[room].selected;
        const url = selectedDirection ?
                `https://${window.location.hostname}/control/${room}/${direction}?direction=${selectedDirection}` :
                `https://${window.location.hostname}/control/${room}/${direction}`;

            console.log("Doing fetch to", url)
	    if (direction === "stop")
                this.showStatus(`Curtain is stopping...`);
            else if (direction === "up")
                this.showStatus(`Curtain is going up`);
            else
                this.showStatus(`Curtain is going down`);

            const response = await fetch(url, { method: 'GET' });
            if (!response.ok) {
                throw new Error(response.statusText);
            }
        } catch (err) {
            this.showError(`Failed to ${direction} curtain: ${err.toString()}`);
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

        fetch(`/register/${room}`).then(response => {
            if (response.status === 404) {
                this.showError(`Room ${room} not found`);
                return;
            }
            if (!response.ok) {
                throw new Error(`Failed to register ${response.status}`);
            }
            return response.json();
        }).then(data => {
            console.log(data);
            console.log(data.length);
            if (data === undefined) return;

            this.favorites.push(room);
            this.roomDirections[room] = {
                directions: data,
                selected: data.length > 1 ? data[0] : null
            };
            this.saveToLocalStorage();
            this.roomInput.value = '';
            this.renderRooms();
        }).catch(error => {
            this.showError(`Error: ${error}`);
        });
    }

    removeRoom(room) {
        this.favorites = this.favorites.filter(r => r !== room);
        delete this.roomDirections[room];
        this.saveToLocalStorage();
        this.renderRooms();
    }

    renderRooms() {
        this.roomsList.innerHTML = '';
        this.emptyState.style.display = this.favorites.length ? 'none' : 'block';

        this.favorites.forEach(room => {
            const directions = this.roomDirections[room]?.directions || [];
            const selected = this.roomDirections[room]?.selected;

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
                <span class="room-number">${room}</span>
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
        setTimeout(() => {
            this.errorDiv.style.display = 'none';
        }, 3000);
    }

    showStatus(message) {
        this.statusDiv.textContent = message;
        this.statusDiv.style.display = 'block';
        setTimeout(() => {
            this.statusDiv.style.display = 'none';
        }, 5000);
    }
}

const curtainControl = new CurtainControl();
