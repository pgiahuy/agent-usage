/* The AI Usage panel UI: every limit is its own raised tile, with the token
 * counts as two tiles side by side underneath.
 *
 * Loaded by extension.js, which always imports the highest-numbered ui-<n>.js.
 * Read the comment there before editing this file in place: an edit here only
 * lands on a logout, whereas a copy at the next number lands on disable/enable.
 *
 * The percentages are CONSUMED, the same direction as the panel's ring and the
 * colour tiers in ring.py: a full bar and a high number both mean trouble.
 * Showing what is left instead was tried and dropped: it read the opposite way
 * from the same bar, and disagreed with the ring sitting next to it.
 */

import GObject from 'gi://GObject';
import St from 'gi://St';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Clutter from 'gi://Clutter';
import Pango from 'gi://Pango';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

// Two revisions of this file can be live in one process, because the previous
// one is still registered when a newer one loads, so GTypes have to be named apart.
const REV = /ui-(\d+)\.js$/.exec(import.meta.url)?.[1] ?? '0';

const CACHE_DIR = GLib.build_filenamev([GLib.get_user_cache_dir(), 'ai-usage']);
const STATE_PATH = GLib.build_filenamev([CACHE_DIR, 'state.json']);
const REFRESH_TRIGGER = GLib.build_filenamev([CACHE_DIR, 'refresh-request']);

// 272px card - 2x10px tile padding - 2x1px tile border. The track cannot just
// x_expand: the fill inside it is sized in px, so the track has to be a known
// width for the two to agree.
const TRACK_W = 250;
const MIN_FILL = 3;   // px, so that any usage at all stays visible
const DUO_W = 133;    // (272 - 6px spacing) / 2
const RING_SIZE = 20;
// Refresh spinner: 20° every 33ms is a turn every 0.6s at about 30fps. Faster
// than that on a 14px glyph stops reading as rotation and just looks like
// flicker, since the arrowhead moves more than its own width per frame.
const SPIN_MS = 33;
const SPIN_STEP = 20;
// The daemon does the actual work, so the spin ends when it writes a new
// state file. If it is not running, nothing will ever arrive, so stop anyway.
const SPIN_CAP_S = 12;
const POLL_SECONDS = 60; // safety net behind the file monitor

const consumed = limit => Math.max(0, Math.min(100, limit.percent ?? 0));

/* ---------------------------------------------------------------- panel pill */

const Pill = GObject.registerClass({GTypeName: `AiUsagePill${REV}`},
class Pill extends St.BoxLayout {
    _init() {
        super._init({style_class: 'ai-usage-pill', y_align: Clutter.ActorAlign.CENTER});
        this._slots = [];
    }

    // Rebuild only when the shape changes; otherwise update in place so the
    // panel does not flicker on every 20-second refresh.
    update(tools) {
        if (this._slots.length !== tools.length) {
            this.destroy_all_children();
            this._slots = tools.map((_, i) => this._addSlot(i > 0));
        }
        tools.forEach((tool, i) => {
            const slot = this._slots[i];
            if (tool.icon && slot.iconPath !== tool.icon) {
                slot.iconPath = tool.icon;
                slot.icon.gicon = Gio.FileIcon.new(Gio.File.new_for_path(tool.icon));
            }
            slot.label.text = tool.badge ?? 'n/a';
            slot.label.style = `color: ${tool.accent};`;
        });
    }

    _addSlot(withSeparator) {
        if (withSeparator)
            this.add_child(new St.Widget({style_class: 'ai-usage-pill-sep'}));
        const box = new St.BoxLayout({style_class: 'ai-usage-mini',
                                      y_align: Clutter.ActorAlign.CENTER});
        const icon = new St.Icon({icon_size: RING_SIZE, y_align: Clutter.ActorAlign.CENTER});
        const label = new St.Label({style_class: 'ai-usage-badge',
                                    y_align: Clutter.ActorAlign.CENTER});
        box.add_child(icon);
        box.add_child(label);
        this.add_child(box);
        return {icon, label, iconPath: null};
    }
});

/* ------------------------------------------------------------- popup pieces */

function tile(extraClass) {
    return new St.BoxLayout({
        style_class: extraClass ? `ai-usage-tile ${extraClass}` : 'ai-usage-tile',
        orientation: Clutter.Orientation.VERTICAL,
    });
}

// name on the left, its reset time beside it, the number pushed to the far
// right. The "%" is a second label rather than markup: Pango sizes are in
// points and the rest of this sheet is in px, so mixing them drifts.
function tileHead(name, note, value, colour) {
    const row = new St.BoxLayout({style_class: 'ai-usage-trow'});
    row.add_child(new St.Label({style_class: 'ai-usage-row-name', text: name,
                                y_align: Clutter.ActorAlign.CENTER}));
    if (note) {
        row.add_child(new St.Label({style_class: 'ai-usage-when', text: note,
                                    y_align: Clutter.ActorAlign.CENTER}));
    }
    row.add_child(new St.Widget({x_expand: true}));
    if (value !== null) {
        const box = new St.BoxLayout({style_class: 'ai-usage-pct-box',
                                      y_align: Clutter.ActorAlign.CENTER});
        box.add_child(new St.Label({style_class: 'ai-usage-pct', text: String(value),
                                    style: `color: ${colour};`,
                                    y_align: Clutter.ActorAlign.CENTER}));
        box.add_child(new St.Label({style_class: 'ai-usage-pct-unit', text: '%',
                                    style: `color: ${colour};`,
                                    y_align: Clutter.ActorAlign.END}));
        row.add_child(box);
    }
    return row;
}

function limitTile(limit) {
    const box = tile();
    const used = consumed(limit);
    box.add_child(tileHead(limit.label, limit.resets, used, limit.colour));

    // A horizontal BoxLayout, not a BinLayout: BinLayout centres the fill, so a
    // short bar floats in the middle of its track instead of starting at the
    // leading edge.
    const track = new St.BoxLayout({style_class: 'ai-usage-track',
                                    y_align: Clutter.ActorAlign.CENTER});
    let width = Math.round(used / 100 * TRACK_W);
    if (used > 0 && width < MIN_FILL)
        width = MIN_FILL;
    track.add_child(new St.Widget({style_class: 'ai-usage-fill',
                                   style: `background-color: ${limit.colour}; width: ${width}px;`}));
    box.add_child(track);
    return box;
}

// Same tile, no bar: used when the provider gives no reading at all.
function noQuotaTile(why) {
    const box = tile();
    box.add_child(tileHead('no quota', why ?? 'local count only', null, null));
    return box;
}

function statTiles(today, week) {
    const row = new St.BoxLayout({style_class: 'ai-usage-duo'});
    for (const [name, totals] of [['today', today], ['7 days', week]]) {
        const box = tile('ai-usage-duo-tile');
        box.add_child(new St.Label({style_class: 'ai-usage-stat-k', text: name}));
        box.add_child(new St.Label({style_class: 'ai-usage-stat-v', text: totals.tokens_h}));
        box.add_child(new St.Label({style_class: 'ai-usage-stat-k',
                                    text: `${fmtInt(totals.reqs)} req`}));
        row.add_child(box);
    }
    return row;
}

function noteRow(text) {
    // Notes must wrap: a provider error can be a whole sentence, and
    // ellipsising it hides the part that says what went wrong.
    const row = new St.BoxLayout({style_class: 'ai-usage-note-row'});
    const label = new St.Label({style_class: 'ai-usage-note', text, x_expand: true});
    label.clutter_text.line_wrap = true;
    label.clutter_text.line_wrap_mode = Pango.WrapMode.WORD_CHAR;
    label.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;
    row.add_child(label);
    return row;
}

function fmtInt(n) {
    return (n ?? 0).toLocaleString('en-US');
}

// The design tracks the tool names out at .14em. St has no letter-spacing, so
// the spacing goes into the string; these are fixed ASCII names, never user text.
function spaced(name) {
    return name.split('').join(' ');
}

/* ------------------------------------------------------------------ indicator */

const Indicator = GObject.registerClass({GTypeName: `AiUsageIndicator${REV}`},
class Indicator extends PanelMenu.Button {
    _init() {
        super._init(0.5, 'AI Usage', false);
        // Marks the button so the stylesheet can strip the panel's own padding
        // and hover paint; see the note beside .ai-usage-panel-button.
        this.add_style_class_name('ai-usage-panel-button');
        this._pill = new Pill();
        this.add_child(this._pill);

        this._body = new St.BoxLayout({style_class: 'ai-usage-card',
                                       orientation: Clutter.Orientation.VERTICAL});
        const item = new PopupMenu.PopupBaseMenuItem({reactive: false, can_focus: false});
        item.add_child(this._body);
        this.menu.addMenuItem(item);

        this._state = null;
        // The timers outlive the actors they touch unless something stops them.
        this.connect('destroy', () => this._stopSpin());
        this._render();
    }

    setState(state) {
        // Whatever triggered this, the numbers on screen are now current, so
        // the spinner has nothing left to wait for.
        this._stopSpin();
        this._state = state;
        this._render();
    }

    // A hand-rolled timer rather than icon.ease(): _render() destroys and
    // rebuilds this icon on every state change, and a chained ease would keep
    // firing its completion callback against an actor that no longer exists.
    _startSpin() {
        if (this._spinTimer)
            return;
        this._spinAngle = 0;
        this._spinTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, SPIN_MS, () => {
            if (!this._spinIcon) {
                this._spinTimer = null;
                return GLib.SOURCE_REMOVE;
            }
            this._spinAngle = (this._spinAngle + SPIN_STEP) % 360;
            this._spinIcon.rotation_angle_z = this._spinAngle;
            return GLib.SOURCE_CONTINUE;
        });
        this._spinCap = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, SPIN_CAP_S, () => {
            this._spinCap = null;
            this._stopSpin();
            return GLib.SOURCE_REMOVE;
        });
    }

    _stopSpin() {
        if (this._spinTimer) {
            GLib.Source.remove(this._spinTimer);
            this._spinTimer = null;
        }
        if (this._spinCap) {
            GLib.Source.remove(this._spinCap);
            this._spinCap = null;
        }
        if (this._spinIcon)
            this._spinIcon.rotation_angle_z = 0;
    }

    _render() {
        this._body.destroy_all_children();
        const tools = this._state?.tools ?? [];

        if (!tools.length) {
            this._pill.update([{accent: '#8b90a0', badge: 'n/a', icon: null}]);
            this._body.add_child(new St.Label({
                style_class: 'ai-usage-note',
                text: 'ai-usage daemon is not running.\nsystemctl --user start ai-usage',
            }));
            return;
        }

        this._pill.update(tools);

        tools.forEach((tool, index) => {
            const block = new St.BoxLayout({
                style_class: index ? 'ai-usage-tool ai-usage-tool-next' : 'ai-usage-tool',
                orientation: Clutter.Orientation.VERTICAL,
            });

            const head = new St.BoxLayout({style_class: 'ai-usage-head'});
            head.add_child(new St.Widget({style_class: 'ai-usage-dot',
                                          style: `background-color: ${tool.accent};`,
                                          y_align: Clutter.ActorAlign.CENTER}));
            head.add_child(new St.Label({style_class: 'ai-usage-tool-name',
                                         text: spaced(tool.name),
                                         style: `color: ${tool.accent};`,
                                         y_align: Clutter.ActorAlign.CENTER}));
            // The refresh control rides in the first header row, right-aligned,
            // which is where the design puts it without costing a whole row.
            if (index === 0) {
                head.add_child(new St.Widget({x_expand: true}));
                head.add_child(this._refreshButton());
            }
            block.add_child(head);

            if (tool.limits.length) {
                if (tool.stale)
                    block.add_child(noteRow(`last known: ${tool.why ?? 'not reachable'}`));
                for (const limit of tool.limits)
                    block.add_child(limitTile(limit));
            } else {
                block.add_child(noQuotaTile(tool.why));
            }

            block.add_child(statTiles(tool.today, tool.week));
            this._body.add_child(block);
        });
    }

    _refreshButton() {
        const icon = new St.Icon({icon_name: 'view-refresh-symbolic', icon_size: 14});
        icon.set_pivot_point(0.5, 0.5);  // spin about its own centre, not a corner
        this._spinIcon = icon;
        const button = new St.Button({style_class: 'ai-usage-refresh',
                                      can_focus: true,
                                      child: icon});
        button.connect('clicked', () => {
            // Touch a file the daemon watches; the shell must never do the work
            // itself, and this avoids spawning a process from the compositor.
            try {
                GLib.file_set_contents(REFRESH_TRIGGER, String(GLib.get_real_time()));
                this._startSpin();
            } catch (e) {
                logError(e, 'ai-usage: could not request a refresh');
            }
        });
        return button;
    }
});

/* ------------------------------------------------------------------------ ui */

export class AiUsageUi {
    constructor(extension) {
        this._uuid = extension.uuid;
    }

    enable() {
        this._indicator = new Indicator();
        Main.panel.addToStatusArea(this._uuid, this._indicator);

        this._file = Gio.File.new_for_path(STATE_PATH);
        this._monitor = this._file.monitor_file(Gio.FileMonitorFlags.NONE, null);
        this._monitorId = this._monitor.connect('changed', () => this._scheduleLoad());

        this._load();
        this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, POLL_SECONDS, () => {
            this._load();
            return GLib.SOURCE_CONTINUE;
        });
    }

    disable() {
        if (this._debounce) {
            GLib.Source.remove(this._debounce);
            this._debounce = null;
        }
        if (this._timer) {
            GLib.Source.remove(this._timer);
            this._timer = null;
        }
        if (this._monitor) {
            this._monitor.disconnect(this._monitorId);
            this._monitor.cancel();
            this._monitor = null;
        }
        this._file = null;
        this._indicator?.destroy();
        this._indicator = null;
    }

    // The daemon writes atomically (temp file + rename), which emits several
    // events in a row; collapse them into one read.
    _scheduleLoad() {
        if (this._debounce)
            return;
        this._debounce = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 120, () => {
            this._debounce = null;
            this._load();
            return GLib.SOURCE_REMOVE;
        });
    }

    _load() {
        let state = null;
        try {
            const [ok, bytes] = this._file.load_contents(null);
            if (ok)
                state = JSON.parse(new TextDecoder().decode(bytes));
        } catch (e) {
            // Missing or half-written file is a normal transient state.
            state = null;
        }
        this._indicator?.setState(state);
    }
}
