# Screenshots

The images referenced from the README and from the landing page.

Nine of the ten files are taken from the current build by one script:

```bash
cd web && npm run shots
```

`web/e2e/shots.mjs` starts the sidecar on a free port with an empty
settings file, writes the invented history from `web/e2e/demo/sessions.json`
through the API, and drives the interface with Playwright against the
installed Google Chrome. The desktop viewport is 1280 by 900 at a device
scale factor of 2, and the phone viewport is 480 by 900 at the same scale.
`SHOTS_OUT` sends the files somewhere else.

| File | What it shows |
| --- | --- |
| `app-empty.png` | The empty state on the desktop: the app bar, the history rail with the search field, and the dashed target that explains what will happen to the recording. |
| `app-empty-mobile.png` | The same empty state at 480 pixels wide, where the rail has fallen under the document and the page has no horizontal scroll. |
| `app-results.png` | The finished document: the summary with its mode chips, the cost of the call, the transcript with the speaker rail and the masked entities in their chips. |
| `app-diarization.png` | The transcript scrolled to the second speaker, with the turn label, the timecode and the entity chips in the running text. |
| `app-search.png` | The search field above the transcript filled with "казначейства", with the matches in amber. |
| `app-settings.png` | The settings panel in the left rail, in place of the document, at the full page height. |
| `app-history.png` | The history row in rename mode: the name has become an input, with the focus ring on it. |
| `app-dark-results.png` | The same document in the dark theme. |
| `app-dark-settings.png` | The settings panel in the dark theme, at the full page height. |

The tenth file, `app-review.png`, shows the screen between the transcript
and the request to the provider: the status band that says nothing has been
sent yet, the whole masked text in the chips, the three focus modes and the
call to action. It is a picture of an earlier build, from the time when the
accent was still the indigo of the shadcn default and the demo recording
was called "pii-demo.wav", and no script in the repository produces it any
more. It is kept because it is the only picture of the pre-send screen, and
it is not referenced from the README.

Every name, phone number, passport and address in the pictures is
invented. The meeting in them does not exist, and the people in it are not
people.
