# Founder decisions

The source of truth. Every ruling Chris makes lands here, dated, in plain
words, with the code that enforces it named beside it. A decision changes
only when Chris says so.

## 2026-10-09: the start

- **Company name:** Event Caliber, for now. The name can change; it lives in
  one setting (`BRAND_NAME` in `.env`, default in `core/config.py`).
- **Legal entity:** CKI, LLC (`LEGAL_NAME`).
- **Repo:** a fresh private repo, `ChrisKennedyImages/cki-convention-social`,
  with its own history. Nothing from any other company's suite is referenced
  anywhere (`tests/test_banned_words.py`).
- **Conventions:** both fan conventions (comic, anime, gaming; no cosplay, 2026-10-11) and
  business and political conferences.
- **Photo library:** Google Drive of chriskimages@gmail.com, read only, signed
  in as Chris (OAuth, `drive.readonly`).
- **Platforms:** Instagram, a Facebook Page and Pinterest, all through this
  company's own Buffer account.
- **Cadence:** one post a day.
- **Posting times:** left to the suite. Starting times, Eastern:
  Instagram about 11:30 on weekdays and 10:00 on weekends, Facebook about
  9:30, Pinterest about 20:30. These come from general industry data on
  engagement, not this account's own numbers; the suite moves toward what
  its own posts show once Buffer reports them.
- **Credits and consent:** one Google Sheet that Chris keeps.
- **Beyond social:** emails to event organizers (each sent only on Chris's
  Approve) and a website on a new domain, with mail sent from an address on
  that domain.
- **Brand:** the suite designs options for Chris to choose from; nothing is
  wired until he picks.
- **What the company sells:** full event coverage: backstage, green room,
  breakouts, before, during and evening events and dinners, portraits,
  exhibition halls and vendors, and immediate delivery of approved images to
  attendees, staff, speakers and presenters.
- **Prices:** vary by event and are not fixed. No post, email or page ever
  states a price; the call to action is a quote request
  (`ai/copy_rules.py`, rule `price`).

## 2026-10-09: second round

- **Official photographer:** none. Chris is not any event's official
  photographer, and there are no booked jobs yet: the company is starting
  back up after four years of caring for his mother. No copy may say or
  hint at an official role, a client list or past bookings that do not
  exist (`ai/copy_rules.py`; the calendar's official box stays unticked).
- **Umbrella:** everything runs under CKI, LLC. Event Caliber is its brand.
- **Domain:** eventcaliber.com, on Cloudflare (`BRAND_DOMAIN`).
- **Brand direction:** Lens (ring monogram, cobalt on graphite, Space
  Grotesk) (`BRAND_DIRECTION=lens`, `render/brand.py`).
- **Booking, built now:** a quote request form on eventcaliber.com that
  lands on the dashboard and on his phone; a drafted reply he edits and
  approves before it sends (he writes any price himself; the drafter never
  does); a public availability calendar that shows booked dates only, with
  no client or event names. The deposit link is built but OFF: no payment
  service yet.
- **Mail:** Cloudflare Email Routing forwards mail for the domain to his
  inbox; a sending service with SMTP sends from the domain.
- **Photo sorting:** Ollama on the Mini sorts the whole library (free). Claude
  looks again only at a photo picked for a post, as the final check for
  minors and personal details. A photo is postable only after that Claude
  check passes (`library/eligibility.py`).
- **Architecture photos:** his exterior and some interior architecture work
  can be used as full building and venue shots: in the daily feed one day a
  week, in the website portfolio, and behind promo graphics. Clearance is
  still per folder, by Chris; readable house numbers and street signs keep a
  photo out.

## 2026-10-10: what the building work may show

- **Architecture is buildings, not rooms.** Chris, after the first building
  contact sheet: the architecture work must **never** include empty rooms,
  bathrooms, closets or anything residential. The sheet of 2026-10-10 was
  full of all four, because the library's building work is largely
  commissioned real estate photography of apartments. **Bars are fine
  anywhere.** What is left is what the work was meant to be: building
  exteriors, and non residential interiors shown as architecture, such as a
  lobby, an atrium, a ballroom or event space, a bar, or a commercial or
  retail interior. Residential is asked as its own question, because a flat's
  hallway and a hotel's hallway are both corridors (`library/classify.py`
  `BANNED_SPACES`, `library/eligibility.py` `building_blocked`).
- **Addresses are fine on the building work.** Amending 2026-10-09: a street
  number or a street name is not a personal detail on Chris's architecture
  photographs, because they are public buildings and he already holds
  releases for them. On a photo of people it still blocks, because there the
  number says where somebody lives (`library/eligibility.py`
  `ADDRESS_DETAILS`). The sort still reads and records them either way.

## 2026-10-10: third round

- **Look:** not Lens. Black, white and greys with a touch of cyan. The first
  site was "not at all dynamic or edgy": rebuilt as a camera viewfinder
  (`site/theme.py`).
- **Logo: Aperture** (Chris, 2026-10-10). A C cut like an open aperture ring
  with a cyan point of light inside it; EVENT in white over CALIBER in grey,
  in Unbounded (`site/marks.py`, `render/brand.py`; `BRAND_MARK=aperture`,
  `BRAND_DIRECTION=aperture`).
- **Image metadata for search:** yes, our own words only (title,
  description, keywords, creator, copyright CKI, LLC, credit); never the
  camera's data or GPS (`render/meta.py`).
- **The crew grows:** Learner, Outreach, SEO, Scout, Chief of staff and Art
  director, each in dry run until switched on; anything that sends or posts
  still waits for Chris's Approve.

## 2026-10-09: going live

- "Merge and make sure live." The first milestone is merged into `main`. The
  site goes live before any photo is cleared: it is built without photos and
  the menu shows only the sections that exist; photos join on the next build
  once folders are cleared and the final check passes (`bin/ccs site build`).
- Going live is one command on the Mini, `scripts/go-live.sh`; it ends with
  `LIVE` only when every page and the booking API pass from the outside.

## 2026-10-11: the Mini updates itself

- "How the fuck do I work on this without a session in terminal on my mini."
  Chris chose auto-update: the updater agent checks GitHub every 10 minutes,
  runs the full suite on anything newly merged to `main`, and only on a green
  run fast-forwards the Mini and restarts the dashboard. Red tests, a checkout
  on another branch or with local changes hold it back. It ships in dry run
  like every agent; Chris switches it live on the Agents page. New service
  files still need one `scripts/go-live.sh` (his Mac password), flagged on the
  Agents page, never attempted.
- Every agent has a Run now button on the Agents page, so nothing day to day
  needs a terminal.
- `scripts/go-live.sh` brings the checkout up to date with GitHub itself before
  it installs anything (`bin/ccs sync`, the updater's way: tested first,
  fast-forward only) and clears the Agents page's ask once the services are
  installed (`bin/ccs launchd installed`). The evening of 2026-10-11 a go-live
  run on a checkout from before the last merge installed the old 6:00 draft
  schedule and said LIVE; `ccs status` now prints where the code stands against
  GitHub main, in capitals when it is behind.

## 2026-10-11: face match delivery, the photos, the look

- **Face match delivery is a lead selling point.** Chris: attendees scan the
  barcode on their lanyard or on posters around the event, fill in three
  short fields and take a quick selfie; every photo any of the photographers
  takes with their face anywhere in it is sent to them right away, with no
  wires. The convention staff or head decides before the event whether to
  offer that to attendees, or to keep it to staff, tailored so each staff
  member receives only the photos of the people they need, internally. The
  offer file, the caption brief, the outreach note, the quote reply and the
  site say it in those plain terms (`offer.json` `on_site_delivery`,
  `ai/claude.py`, `outreach/draft.py`, `site/build.py`).
- **The photos are original, no AI at all.** Every photo in the library is an
  original photograph; Chris and his brother own the rights to all of them.
  The suite never makes, alters or shows a generated image as if it were a
  photograph, samples included: design samples use his real photos.
- **The look moves.** After the first round of post designs ("You just made a
  fucking grid"), Chris sent the direction: photos as physical cards in depth
  and motion (a hand of cards fanned across the frame with the focused one
  lifted out, a spinning ring, a spotlight rail where the middle frame opens
  out with its caption, numbered folders), not flat tiles.

## 2026-10-11: only what Chris approves, and a dashboard he can find his way round

- **Only approved photos are ever used.** Chris: "When I go to the library, I
  only want to choose what I approve and if it's not approved then don't use it
  yet or at all." A photo is approved when he taps Use on it or clears its
  folder. Posts, the website and the design samples take approved photos only
  (`library/eligibility.py`, `render/design_samples.py`); unapproved photos show
  only where he chooses: Photos, To review, and the library report sheets.
- **Four tabs.** "The navigation is not intuitive or smart!" Today, Photos,
  Bookings and More, each with one row of its own pages; every folder page links
  back to the folder list and can clear or exclude the whole folder in place
  (`dashboard/app.py` `SECTIONS`).

## 2026-10-11: the daily post uses the new designs

- "Switch to new designs and it's ok to use 1 photo too sometimes." The daily
  draft rotates through the motion set: Monday spotlight (3 or more photos),
  Tuesday single, Wednesday (the building day) single, Thursday carousel (4 or
  more), Friday fan (5 or more), Saturday single, Sunday face match. A day whose
  design needs more approved photos than pass the final check is a single photo
  day. Every photo on a post is approved and passes the final check
  (`agents/content.py` `DESIGNS`).
- Reels stayed in the design samples until a music track was added (moved into
  the rotation the same day, below).

## 2026-10-11: reels, with music, in the rotation

- "Let's get the music and everything working (video format too)." Saturday is
  a reel once a music track is on (Photos, Design, Music for reels): the rooms
  reel and the face match reel take turns by week, on 4 to 6 approved photos
  that pass the final check, one per room before any room repeats. With no
  track Saturday stays a single photo: a silent reel is never made. A reel that
  cannot be made becomes a carousel of the same photos and says why
  (`agents/content.py` `DESIGNS`, `reel_kind`).
- The music is only ever a track Chris added with its record of where it came
  from and what it allows; it rides the reel faded in and out (`music.py`,
  `render/reel.py` `encode`).
- Instagram and Facebook get the reel as a video post with its cover; Pinterest
  gets a 2:3 card of the lead photo. Buffer's video format is not written from
  memory: before a reel is sent the publisher reads the video fields from
  Buffer's live schema, and if Buffer asks for anything the code cannot fill,
  nothing is uploaded and nothing is sent (`agents/publisher.py`,
  `buffer/payloads.py` `video_asset`). Like every post, a reel waits for
  Chris's Approve; the first one he approves is the live check of the format.

## 2026-10-11: one Anthropic key, Buffer ready to link, a dashboard that stays current

- **The Anthropic key is shared, by Chris's choice.** "Use my Anthropic key from
  [my other suite's] .env (DO NOT TOUCH ANYTHING IN THAT ENV)." This amends the
  brief's "no Anthropic key shared"; nothing else from that suite is used.
  `bin/ccs copy-key ANTHROPIC_API_KEY --from <that file>` only reads the file,
  checks it is byte for byte unchanged, saves the key in this suite's own
  `.env` and never prints it (`cli.py` `cmd_copy_key`). This suite's own spend
  still stops at `AI_MONTHLY_CAP_USD`.
- **Buffer plumbing before the account.** "A Buffer channel is not set up for
  this yet, but definitely get the plumbing in so we can just add it quickly
  when I do." The Buffer page (More, Buffer) takes it from a key to posting:
  find the channels, Use on each of this company's own accounts (nothing links
  by itself), the Pinterest board from Buffer's own list, and a check of the
  reel video format. A key that sees more than one Buffer organization posts
  nowhere until Chris chooses this company's (`buffer/client.py`
  `organization_id`, `dashboard/app.py`).
- **The dashboard stays current.** "Dashboard is still the old one." Every
  updater run asks the running dashboard which commit it serves and restarts it
  when it lags the checkout; if it still lags after one restart, Chris gets the
  one command that restarts it (`agents/updater.py` `ensure_dashboard`).

## 2026-10-11: the Photos tab, the Mini's disk

- **"Photos tab is dead."** Every visit loaded the whole library twice before
  showing 48 photos. The tab now reads one page from the database, with the
  same rules and order (`dashboard/app.py` `photo_page`, pinned against the old
  lists in `tests/test_photos_tab.py`). A page that fails says what failed and
  records it on the Agents page; when Drive is signed out the Photos tab says
  that is why the pictures do not load.
- **"The mini can't hold all these high res images."** Originals stay in Google
  Drive. The Mini keeps small previews, the full-size copy of each photo picked
  for a post, and the rendered posts; the company's bucket gets only the files
  of posts that go out. Every night the backup agent deletes the copies nothing
  needs any more, only inside the data folder, and says how much disk is free
  (`storage.py`).
- **Music in an .mp4.** An audio-only .mp4 is taken as a track; a file with no
  sound is refused (`music.py`).

## 2026-10-11: never which event, never who

- "Because A LOT of the images are ACU and CPAC (the same company) i want to
  make sure the captions don't say the specific event or person." No public
  word names the event, the organization behind it or any person, and no
  @handle tags anyone: not the captions, not the line printed on the post
  image, not the search fields inside the image files, not the website's photo
  text. They say the kind of event (a conference, a fan convention) and what
  the photo shows. The writers are never given the event's name or a credit;
  the copy rules block every name the suite knows (the two Chris named, every
  event name the sorting or the calendar recorded, everyone on the credits
  sheet), and both Approve and the publisher's last check enforce it
  (`ai/names.py`, `ai/copy_rules.py` rule `names`). Website text written
  before this is written again. Private mail to an organizer about their own
  event is not public copy and is not covered.

## 2026-10-11: no cosplay; captions built for search

- **No cosplay, anywhere.** "We are going to NOT do ANY COSPLAY ... erase that
  from everything." The offer, the website, the quote form, the caption and
  outreach prompts, the search text and the designs no longer mention it
  (pinned by `tests/test_seo_captions.py`). The photo sorter still tells
  costume photos apart, only so that none is ever used or offered for review
  (`library/eligibility.py` `NOT_OFFERED`).
- **Captions are built for search.** "Make sure the captions are SEO optimized
  painstakingly." Every post gets a search plan from what it shows (the kind of
  event, the room, the design; never a name): one search phrase, word for word
  in the first sentence of every caption and above Instagram's fold; related
  phrases in the body; the place when `SERVICE_AREA` is set (Keys page); five
  hashtags on Instagram and three on Pinterest, chosen in the code, specific
  first, none naming anyone; the quote link on Facebook and Pinterest; a pin
  title under 100 characters that opens with the phrase; alt text on every
  image where Buffer's live schema offers a field for it. A draft that misses
  is written once more with the misses named; after a second miss the
  template, which meets the plan by construction, stands in (`ai/seo_plan.py`,
  `agents/content.py` `write_captions`). Pins link to the quote page.

## 2026-10-11: the mock ups make themselves

- "Where are the mock ups with the approved images". The design samples on
  Chris's approved photos are made by themselves: the hourly scanner starts
  them whenever the approved photos they would use change. The Design card
  (Photos, Design) always says what happened: being made, ready, or not made
  and why, with how many approved photos are ready and how many the sorter
  still has to look at (it does approved photos first). A failure is also on
  the Agents page. The samples use every approved photo, not four per event
  (`render/design_samples.py` `auto`, `cli.py` `cmd_design`).

## 2026-10-11: what pings the phone

- "I haven't received any ntfy." Until now only the watchdog's alerts and the
  morning brief pinged. Now a post ready to approve pings with a link to the
  draft, a post that went out pings with a link to it, and the Keys page has a
  Send a test ping button that says whether the ping was sent or why not
  (`core/notify.py`, `agents/content.py`, `agents/publisher.py`). A ping needs
  `NTFY_TOPIC` on the Keys page and the agent live; the watchdog still pings
  failures within the hour.
## 2026-10-11: what the first real alerts found

- The watchdog's first pings (4:38 PM) named two faults. The dashboard ran out
  of file handles on the Photos tab (macOS gives a background process 256; 48
  previews at once need more): every process now raises its own limit at
  start, a preview is fetched from Drive once however many requests ask, at
  most six fetches run at a time, and the file is written whole before anyone
  reads it (`core/limits.py`, `dashboard/app.py` `cached_thumb`). The scanner's
  free sort pass ran for hours (about half a minute a photo, 500 a run) and
  nothing else of its hourly work happened meanwhile: a run now stops after
  `SCAN_BUDGET_MINUTES` (45) and sorts the rest next hour, approved folders
  first; the watchdog says "started … and has not finished" for a run still
  going, not "last ran" (`library/classify.py` `sort_pass`, `agents/watchdog.py`).

## 2026-10-11: what a photo shows is Claude's word, and Chris's

- "It calls a stage shot a portrait which, never can happen!" The free local
  sorter's shot type is a guess that reached the captions, the alt text and the
  image's search fields. Claude's final check, which already looks at every
  photo picked for a post in full, now says what the photo shows (a stage shot
  is stage_panel however close the framing) and that word replaces the guess
  everywhere it is read. On a draft each photo shows its word with a "Wrong?
  Fix and draft again" control: Chris's word is written everywhere, the draft
  is set aside and a new one is made at once (`library/classify.py`
  `final_check`, `set_shot_type`; `dashboard/app.py`).
- The learner weighs kinds of photo by what the post numbers say once Buffer
  reports them; it does not learn from corrections. A correction is applied,
  not learned.
- "Where I work is everywhere": `SERVICE_AREA` takes `nationwide`, a home base
  such as `Washington DC`, or both as `Washington DC, nationwide` ("Based in
  Washington DC, covering events nationwide.") (`ai/seo_plan.py`).
## 2026-10-11: buildings apart from events; the draft at 8

- "Architecture images should be separated from event/convention photos (even
  though we're using them for the same thing)." To review and Approved each
  show Events and Buildings as two lists with their own counts; a building is
  what the sorter called architecture (`dashboard/app.py` `SUBJECTS`).
- The daily draft runs at 8:00, not 6:00. It drafts the next day's post, so
  the hour changes nothing about when posts go out; it only sets when the
  draft and its ping arrive (`launchd/…content.plist.template`, one
  `scripts/go-live.sh` on the Mini to take effect).

## 2026-10-11: nothing includes anything

- On a draft that said conference photography "includes portraits like this
  one, shot on site in a few minutes. Colored gradient background, one chair,
  and a short line of attendees who all leave with a new headshot": "Suite
  wide - NOTHING INCLUDES ANYTHING!!!!! Don't ever say something you don't
  know or don't ask me about my own company!!!!" Public text says only what
  `offer.json` and Chris have stated. Nothing about what a service includes
  or comes with, how a shoot is set up, how long anything takes, what anyone
  leaves with, packages or turnaround. A detail the suite does not have is a
  question to him, never a sentence. The gate (`ai/copy_rules.py`, rule
  `claims`) blocks it on every surface: captions, the publisher door, the
  dashboard, outreach mail, quote replies, the site and the photo text; the
  writer is told the rule and the template describes only the coverage he
  listed.
- Then, sharper: "You need to keep to specifics and not talk about what is
  offered or what is a service, specifically in captions and social media or
  anything public. That's between the client and I!" A post is about the
  photo: what it shows, where in the event, the moment; never the company's
  services, coverage, delivery or what a client gets. Rule `offer` in the gate
  runs on every social surface (captions, the dashboard, the door, the cards,
  the reels); the writer's prompt no longer describes the company's services
  at all; the template says the scene and the byline; the cards say the room
  and what is shown. The face match post (Sundays) and the face match reel
  are retired: they explained the delivery service. Sunday is a single photo;
  the Saturday reel is the rooms reel. The website keeps the coverage list
  from `offer.json` that he saw go live; whether that stays is his to say.

## 2026-10-11: never a wedding; every photo judged on its own

- "The main photo when you open the website is from a damn wedding! That one
  needs to be the best of the best and not a wedding! Don't get stuck on
  certain photos. They get judge individually not against anything but
  itself." The local sorter had called a wedding reception an event. Now the
  sorter and Claude's final check both say what kind of occasion a photo is
  from (fan, business, wedding, private, unknown); a wedding or a private
  occasion is never a candidate, never eligible, never in the samples, never
  offered for review. The website picks each photo on its own merit: the
  strongest frame first (sharp, lit, a moment), a known conference or
  convention before an unknown kind; a photo Claude has not yet judged for
  its kind gets that check during the site build, up to twelve a build. The
  live daily draft re-checks every photo it picks, so a wedding never reaches
  a post either.

## Standing rules from the brief

- Nothing publishes without Chris's Approve on the dashboard, until he says
  otherwise. Every agent that sends or publishes starts in dry run
  (`core/settings.py`).
- Nothing in Drive is ever modified, moved, renamed or deleted
  (`drive/`, pinned by `tests/test_drive_readonly.py`).
- No photo is eligible until Chris clears its folder or the photo itself.
  Never post anyone who may be a minor. A do-not-use list is honoured
  everywhere.
- Never claim to be a convention's official photographer or any affiliation
  unless Chris confirms it for that event (`ai/copy_rules.py`, rule
  `affiliation`).
- Captions and copy: plain, short sentences, no dashes, never promise what
  the system does not do today.
