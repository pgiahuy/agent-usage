/* Preferences for Agent Usage, shown by the Extensions app.
 *
 * Runs in its own process, not in the shell, so the ui-<n>.js reload trick
 * does not apply here: the Extensions app loads this file fresh each time.
 */

import Adw from 'gi://Adw';
import Gtk from 'gi://Gtk';
import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

// tag, as the collector and the state file name it; and the label shown here.
const TOOLS = [['claude', 'Claude Code'], ['kimi', 'Kimi Code']];

// [value stored in the setting, label shown]
const LAYOUTS = [
    ['tiles', 'Tiles'],
    ['compact', 'Compact'],
    ['numbers', 'Large numbers'],
];
const PILL_STYLES = [
    ['ring', 'Ring and percentage'],
    ['text', 'Text only'],
];

export default class AgentUsagePreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();
        window._settings = settings;  // keep it alive as long as the window

        const page = new Adw.PreferencesPage();
        page.add(this._toolsGroup(settings));
        page.add(this._appearanceGroup(settings));

        const group = new Adw.PreferencesGroup({
            title: 'Collector',
            description: 'Token counts update every 20 seconds regardless.',
        });

        const key = settings.settings_schema.get_key('quota-interval');
        const [, range] = key.get_range().recursiveUnpack();
        const row = Adw.SpinRow.new_with_range(range[0], range[1], 1);
        row.title = 'Quota check interval';
        row.subtitle = "Minutes between checks of each plan's usage";
        row.value = settings.get_uint('quota-interval');
        row.connect('notify::value', () => {
            const v = Math.round(row.value);
            if (settings.get_uint('quota-interval') !== v)
                settings.set_uint('quota-interval', v);
        });
        settings.connect('changed::quota-interval', () => {
            row.value = settings.get_uint('quota-interval');
        });

        group.add(row);
        page.add(group);
        window.add(page);
    }

    _appearanceGroup(settings) {
        const group = new Adw.PreferencesGroup({title: 'Appearance'});
        group.add(this._choiceRow(settings, 'popup-layout', 'Popup layout', LAYOUTS));
        group.add(this._choiceRow(settings, 'pill-style', 'Panel', PILL_STYLES));
        return group;
    }

    _choiceRow(settings, key, title, choices) {
        const row = new Adw.ComboRow({
            title,
            model: Gtk.StringList.new(choices.map(([, label]) => label)),
        });
        const sync = () => {
            const i = choices.findIndex(([value]) => value === settings.get_string(key));
            row.selected = Math.max(0, i);
        };
        row.connect('notify::selected', () => {
            const value = choices[row.selected]?.[0];
            if (value && value !== settings.get_string(key))
                settings.set_string(key, value);
        });
        settings.connect(`changed::${key}`, sync);
        sync();
        return row;
    }

    _toolsGroup(settings) {
        const group = new Adw.PreferencesGroup({
            title: 'Tools',
            description: 'A hidden tool leaves the panel and the popup, and the collector stops reading its logs and asking its quota API.',
        });
        const rows = TOOLS.map(([tag, label]) => {
            const row = new Adw.SwitchRow({title: label});
            row.connect('notify::active', () => {
                const hidden = new Set(settings.get_strv('hidden-tools'));
                if (row.active)
                    hidden.delete(tag);
                else
                    hidden.add(tag);
                const next = TOOLS.map(([t]) => t).filter(t => hidden.has(t));
                if (next.join() !== settings.get_strv('hidden-tools').join())
                    settings.set_strv('hidden-tools', next);
            });
            group.add(row);
            return [tag, row];
        });

        // The last tool still shown cannot be switched off: an empty panel
        // would only look broken.
        const sync = () => {
            const hidden = new Set(settings.get_strv('hidden-tools'));
            const shown = rows.filter(([tag]) => !hidden.has(tag)).length;
            for (const [tag, row] of rows) {
                row.active = !hidden.has(tag);
                row.sensitive = !(row.active && shown === 1);
            }
        };
        settings.connect('changed::hidden-tools', sync);
        sync();
        return group;
    }
}
