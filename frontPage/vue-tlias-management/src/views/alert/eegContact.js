const INVALID_QUALITY_LEVELS = new Set(['no_contact', 'bad_contact', 'poor', 'unknown'])

export function isInvalidEegContact(payload = {}) {
  return payload.status === 'no_contact'
    || payload.status === 'poor_signal'
    || INVALID_QUALITY_LEVELS.has(payload.quality_level)
}
