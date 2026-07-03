/**
 * Shared Icon Picker Component
 *
 * Usage:
 *   import { showIconPicker } from '../icon-picker.js';
 *   showIconPicker(currentEmoji, callback, title?)
 *   - currentEmoji: the currently selected emoji string (or '—' / '' for none)
 *   - callback(selectedEmoji): called with the selected emoji ('' for no icon, or the emoji string)
 *   - title: optional dialog title (default: 'Choose an Icon')
 */

const ICON_PICKER_EMOJIS = [
    '⏰', '❌', '⚡', '✔️', '✅', '🇺🇸', '🌍', '🌎', '🚀', '💨',
    '🔒', '🛡️', '✨', '★', '⭐', '🏆', '💎', '🎯', '💪',
    '❤️', '💚', '💙', '🧡', '💜', '🤍', '🖤', '💛',
    '📦', '🚚', '✈️', '🎁', '💰', '💵', '🏷️', '🔥',
    '👍', '👌', '🤝', '🙌', '💯', '🎉', '🌟', '⚙️',
    '🔔', '📣', '💬', '📱', '🖥️', '🌿', '♻️', '🌱',
    '📧', '✉️', '📩', '💊', '🧴', '🏠', '🔗', '📋',
    '👑', '💫', '🌠', '🙏', '☮️'
];

/**
 * Show the icon picker modal.
 * @param {string} currentEmoji - Currently selected emoji ('' or '—' = none)
 * @param {function} callback - Called with selected emoji string ('' for no icon)
 * @param {string} [title='Choose an Icon'] - Dialog title
 */
export function showIconPicker(currentEmoji, callback, title) {
    // Remove any existing picker
    const existing = document.getElementById('sharedIconPickerOverlay');
    if (existing) existing.remove();

    const dialogTitle = title || 'Choose an Icon';
    const noIconSelected = !currentEmoji || currentEmoji === '—';

    const noIconHtml = `<button type="button" class="emoji-picker-item no-icon-option ${noIconSelected ? 'selected' : ''}" data-emoji="" title="No icon">—</button>`;

    const emojisHtml = ICON_PICKER_EMOJIS.map(emoji =>
        `<button type="button" class="emoji-picker-item ${emoji === currentEmoji ? 'selected' : ''}" data-emoji="${emoji}">${emoji}</button>`
    ).join('');

    const overlay = document.createElement('div');
    overlay.id = 'sharedIconPickerOverlay';
    overlay.className = 'emoji-picker-overlay';
    overlay.innerHTML = `
        <div class="emoji-picker-dialog">
            <div class="emoji-picker-header">
                <h3>${dialogTitle}</h3>
                <button type="button" class="emoji-picker-close">
                    <svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                    </svg>
                </button>
            </div>
            <div class="emoji-picker-grid">
                ${noIconHtml}
                ${emojisHtml}
            </div>
        </div>
    `;

    document.body.appendChild(overlay);

    // Close on overlay background click
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) overlay.remove();
    });

    // Close button
    overlay.querySelector('.emoji-picker-close').addEventListener('click', () => overlay.remove());

    // Emoji selection
    overlay.querySelectorAll('.emoji-picker-item').forEach(btn => {
        btn.addEventListener('click', () => {
            const selectedEmoji = btn.dataset.emoji;
            overlay.remove();
            if (typeof callback === 'function') callback(selectedEmoji);
        });
    });
}
