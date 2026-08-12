/* AI Usage — Claude Code + Kimi Code usage in the GNOME top bar.
 *
 * This file is a loader and nothing else. Do not put UI in it.
 *
 * GJS caches an imported module by its URI for the life of the shell process,
 * and the shell imports this path once, so editing this file changes nothing
 * until the next logout. The UI therefore lives in ui-<n>.js: enable() imports
 * the highest-numbered one it finds, which is a URI the process has not seen,
 * so a plain `gnome-extensions disable/enable` really does load new code.
 *
 * Ship a UI change by writing ui-<n+1>.js. Stylesheets need no such trick —
 * the shell reloads stylesheet.css on every enable.
 *
 * Everything else about this extension is presentation only: all parsing and
 * every network call live in the ai-usage Python daemon, which writes
 * ~/.cache/ai-usage/state.json.
 */

import Gio from 'gi://Gio';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

function newestUi(path) {
    const children = Gio.File.new_for_path(path).enumerate_children(
        'standard::name', Gio.FileQueryInfoFlags.NONE, null);
    let best = null;
    let bestN = -1;
    let info;
    while ((info = children.next_file(null)) !== null) {
        const match = /^ui-(\d+)\.js$/.exec(info.get_name());
        if (match && Number(match[1]) > bestN) {
            bestN = Number(match[1]);
            best = info.get_name();
        }
    }
    children.close(null);
    return best;
}

export default class AiUsageExtension extends Extension {
    async enable() {
        const name = newestUi(this.path);
        if (!name)
            throw new Error(`ai-usage: no ui-<n>.js in ${this.path}`);
        const {AiUsageUi} = await import(`file://${this.path}/${name}`);
        this._ui = new AiUsageUi(this);
        this._ui.enable();
    }

    disable() {
        this._ui?.disable();
        this._ui = null;
    }
}
