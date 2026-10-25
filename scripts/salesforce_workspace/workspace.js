import { LightningElement } from 'lwc';
__RECORD_IMPORT__

export default class MimWorkspace extends LightningElement {
    frontendUrl = __FRONTEND_URL__;
    objectOptions = __OBJECT_OPTIONS__;
    bridgeEnabled = __BRIDGE_ENABLED__;
    objectName = '';
    recordId = '';
    recordOptions = [];
    message = '';
    busy = false;
    frameReady = false;
    connectedCallback() {
        this.objectName = this.objectOptions[0]?.value || '';
        this.onBridgeMessage = event => {
            const frame = this.template.querySelector('iframe');
            if (event.origin === new URL(this.frontendUrl).origin && event.source === frame?.contentWindow && event.data?.type === 'lifeaftercode.ready.v1') {
                this.frameReady = true;
            }
        };
        window.addEventListener('message', this.onBridgeMessage);
    }
    disconnectedCallback() { window.removeEventListener('message', this.onBridgeMessage); }
    objectChanged(event) { this.objectName = event.detail.value; this.recordId = ''; this.recordOptions = []; }
    recordChanged(event) { this.recordId = event.detail.value; }
    frameLoaded() { if (this.bridgeEnabled && !this.frameReady) this.message = 'Waiting for the hosted record receiver. Check its configured Salesforce parent origin.'; }
    get sendDisabled() { return this.busy || !this.recordId || !this.frameReady; }
    async loadRecords() {
        this.busy = true; this.recordId = ''; this.recordOptions = []; this.message = 'Reading Salesforce records…';
        try {
            const rows = await __RECORD_READER__({objectName: this.objectName, recordId: null});
            this.recordOptions = rows.map(row => ({label: row.Name || row.Id, value: row.Id}));
            this.message = rows.length ? 'Select a record, then send its approved fields to the hosted workspace for review.' : 'No readable records. Add or import incident records first.';
        } catch (error) { this.message = error.body?.message || 'Salesforce record read failed'; }
        finally { this.busy = false; }
    }
    async sendRecord() {
        this.busy = true; this.message = 'Rereading the selected record…';
        try {
            const rows = await __RECORD_READER__({objectName: this.objectName, recordId: this.recordId});
            if (rows.length !== 1) throw new Error('Record is no longer readable');
            const frame = this.template.querySelector('iframe');
            frame.contentWindow.postMessage({type: 'lifeaftercode.incident.v1', object: this.objectName, record: JSON.parse(JSON.stringify(rows[0]))}, new URL(this.frontendUrl).origin);
            this.message = 'Selected record sent to the configured company frontend. Review its recommendation below. No update or approval was made.';
        } catch (error) { this.message = error.body?.message || error.message || 'Salesforce record read failed'; }
        finally { this.busy = false; }
    }
}
