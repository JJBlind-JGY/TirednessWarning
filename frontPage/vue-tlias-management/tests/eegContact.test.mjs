import test from 'node:test'
import assert from 'node:assert/strict'

import { isInvalidEegContact } from '../src/views/alert/eegContact.js'

test('invalid EEG contact states suppress wave display', () => {
  assert.equal(isInvalidEegContact({ status: 'no_contact' }), true)
  assert.equal(isInvalidEegContact({ status: 'poor_signal' }), true)
  assert.equal(isInvalidEegContact({ status: 'online', quality_level: 'bad_contact' }), true)
  assert.equal(isInvalidEegContact({ status: 'online', quality_level: 'good' }), false)
})
