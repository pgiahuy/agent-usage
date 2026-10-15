/* Preferences for Agent Usage, shown by the Extensions app.
 *
 * Runs in its own process, not in the shell, so the ui-<n>.js reload trick
 * does not apply here: the Extensions app loads this file fresh each time.
 */

import Adw from 'gi://Adw';
import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

export default class AgentUsagePreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();
        window._settings = settings;  // keep it alive as long as the window

        const page = new Adw.PreferencesPage();
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
}
