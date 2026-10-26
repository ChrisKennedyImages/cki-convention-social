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
- **Conventions:** business, corporate and association conferences, conventions
  and trade shows, galas and award dinners. Fan conventions (comic, anime,
  gaming) are shot when someone asks by email, never advertised or named: off
  every public surface and out of the scout's search since 2026-10-12, their
  photos used as plain convention photos (no cosplay since 2026-10-11).
  Political work is taken when it comes, never what the company is positioned
  as.
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
  Bookings and More (Settings since 2026-10-15), each with one row of its own pages; every folder page links
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
  (`render/design_samples.py` `auto`, `cli.py` `cmd_design`). Replaced on
  2026-10-15 by the designed drafts on Today: the samples are no longer made
  by themselves.

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

## 2026-10-11: the website's main photo, and no one event first on everything

- "The main photo needs to be the most colorful and dynamic photo - a wide
  stage panorama shot or a very powerful trump shot. And we need to not have
  CPAC and ACU the first thing on everything." The hero is chosen among the
  strongest eligible landscape frames by its own score: strength, colour and
  punch measured from the picture, a stage or panel, a wide frame
  (`site/build.py` `hero_score`). Chris can also pick it himself: Photos tab,
  Approved, "Site hero" on a photo; his pick wins while the photo is usable,
  and tapping it again hands the choice back. The site's grid and the design
  samples are spread across events, one per event before any event repeats.
  The daily draft already rotates events (`variety_days`).

## 2026-10-12: preferably not political

- "Preferably not political but will do if they're paying." Political work
  is taken when it comes; it is never what the company is positioned as. No
  public text, prompt or search names political conferences as the work:
  the site, the offer file, the quote form, the caption writer, the photo
  text and the scout say business, corporate and association conferences,
  conventions, galas and award dinners. The sorter still recognises a
  political conference as business work, so those photos are used like any
  other.

## 2026-10-12, late: the site goes live by itself; the panorama; no fan conventions; portraits are headshots

- "we will fix all tomorrow or do what you can without needing me to respond
  or terminal anything." So nothing here waits for a terminal:
  - **eventcaliber.com follows the code.** `ccs site deploy` is the build, the
    wrangler deploy with the untracked `wrangler.live.jsonc` that go-live
    leaves behind, and the check from outside (`site/deploy.py`). The updater
    runs it when a merge changes a site file, and once when the suite has never
    deployed the site; `scripts/go-live.sh` uses the same command. A deploy
    that fails is an error on the Agents page and is not retried by itself for
    that commit. **Publish the site**, a button on Photos, Approved, runs it from
    a phone after the hero or the approved photos change; the Website card
    there says what happened.
  - **The home page photo.** "the home page image is not the correct photo":
    the wide stage panorama he sent in the chat ships with the code as
    `site/hero.jpg` (re-encoded, no camera data) and is the hero whenever
    nothing has been sent from the phone; Claude checks it like any upload. A
    phone upload wins over it; Remove hands back to it.
  - **"We are going to get rid of 'fan conventions'."** Off every public
    surface: the offer file, the quote form, the captions and keywords, the
    photo text, the search metadata, the brand note, the scout's search brief
    (it leaves fan conventions out) and the dashboard's kind menus. His ruling,
    the same night: **"The fan photos go to plain conventions."** They are
    used like any convention photo, in posts and on the site, and every public
    word about them says convention. **"We will shoot a fan convention, but we
    are not going to advertise it or say it. People can email directly if they
    want us for that."** So the sorter keeps the tag (the photos can be told
    apart) and nothing is set aside; no public surface, search or outreach
    ever offers or names fan conventions.
  - **"Portraits and headshots are the same."** One coverage row, Portraits.
    One shot type, portrait; rows the sorter had called "headshot" are
    portraits (migration 0063), and every reader says Portrait.

## 2026-10-12, late: search engines

- "And yet no site map or Google search indexing." The sitemap and robots.txt
  have been built and checked from outside since 2026-10-09; what was missing
  is the telling. Now: the Google Search Console HTML tag goes on every page
  from the Keys page (`GOOGLE_SITE_VERIFICATION`), the sitemap carries each
  page's true last-changed date (a content record under the data root, never
  the build date), the first publish makes an IndexNow key (`INDEXNOW_KEY`,
  hosted at `/<key>.txt`) and every live publish tells Bing, Yandex and the
  other IndexNow engines which pages to read again (`seo/indexnow.py`). A
  ping that fails never fails a publish; the Website card says so. The one
  step only Chris can do, from his phone: add the property in Search Console,
  paste the tag, publish, press Verify, submit `sitemap.xml` (docs/SETUP.md,
  8a). Google is not in IndexNow and its Indexing API is not for this kind of
  site, so there is no way to make Google index it without that step.

## 2026-10-12, morning: captions mend themselves

- "the captions should auto correct themselves with the warnings they gave
  me before approval. I don't want to change any captions." A draft in the
  queue whose captions break a rule now (the rules grew after it was written)
  is rewritten by the suite, never by him: the content agent mends every open
  draft at the start of each run, the draft page mends one the moment he opens
  it, and Approve mends before it would ever refuse. The writer gets the
  rule's own words as the correction, twice, and the template stands in after
  that (`agents/content.mend_captions`). The page says what was rewritten and
  why; the old text is kept in the draft's record.

## 2026-10-12, morning: a morning with no draft is said out loud

- "the render didn't land this morning at 8am." A content run that drafts
  nothing used to end in a quiet summary line: no ping, no error, and the
  final check's two quiet reasons (the monthly AI cap, no key) returned
  nothing and said nothing. Now the run records the reason as an open error
  on the Agents page and pings the phone ("no post drafted for Tuesday", the
  reason, a tap to the Agents page), once per reason while it stands; the
  cap and a missing key are errors the moment they bite (`classify.look`).
  "Already drafted" stays quiet, since it is not a failure.

## 2026-10-12, morning: a name in the photo is fine

- Approved photos sat marked "shows personal details: document" and "screen"
  (a book cover with its author's name, a card in a portrait). "If they're
  wearing a name badge or there's a name in the photo it's fine to use." So a
  name badge, and the screens and documents the sorter flags at an event (a
  book cover, a program, a slide, signage: a name or a title), never keep a
  photo out of anything (`eligibility.NAME_DETAILS`), and the sorter and the
  final check are told that private information on a screen or paper means a
  message, an email or a form, never a title or a name. A plate, a house
  number or a street sign on a photo of people still keeps it out, as does
  anyone who may be under 18. Photos already flagged need no new look: the
  gate reads the stored flags with the new rule.

## 2026-10-12, late morning: the hero he sends is the hero

- "That's still not the ... landing page photo I uploaded on the dashboard."
  The photo he sends from the Photos page was held behind Claude's look (the
  under-18 rule on a crowd, or no look at all when the cap is reached), and
  the build fell back to its own pick while the card said why. That was the
  suite's design, not his law: his own photo, chosen by him, for his own
  site, is the hero, full stop (`site/hero.py`). Claude still looks at it
  once per file, for the alt text and a note on the card (anyone who may be
  under 18, a readable plate, a wedding), never to hold it back. Sending,
  removing or picking a hero on the dashboard publishes the site by itself,
  so there is no second button and no terminal.

## 2026-10-12, midday: exhibition halls, vendors and booths are one thing

- "Exhibition Halls, vendors and booths are all the same thing." One coverage
  row, Exhibition halls, on the site and the quote form; one shot type,
  `vendor_hall` (rows the sorter had called "booth" are the hall, migration
  0064), and every reader says Exhibition hall. Like portraits and headshots
  the same morning.

## 2026-10-12, afternoon: delivery is a feature; portraits are backstage, lit on site

- "Don't say instant delivery by 'facematch' and don't give the steps in
  which they [need] to do in order to receive the instant delivery. Again,
  too specific and it's a feature not the entire product." Nowhere public
  (the site, the quote reply, the organizer email): no "face match", no
  badge, no selfie, no steps. The site says photos can reach the people in
  them while the event is on, and that the photography is the work; the
  offer row is "Instant delivery during the event"; the quote question asks
  whether photos go out during the event and to whom.
- "A lot of the times the portraits are backstage for the event speakers and
  VIP etc, not the attendees. Some conventions want portraits for all
  attendees but that is kind of a different product. We do really stylized
  and professional portraits: all the lighting and color is done with
  onsite professional lighting (sometimes lighting we create or build
  ourselves) and color gels; no post editing is needed, or very limited."
  The site's Portraits row carries that in one line (the offer file's
  `note`); the portrait card says "Speakers and guests, backstage."; the caption
  writer is told the same and told never to say every attendee gets one.
  Attendee portraits are not advertised.

## 2026-10-13: never CPAC, never the ACU, never an affiliate

- "Also, never outreach to CPAC or the ACU or any affiliates! NEVER and
  that's a hard rule." The rule is code, not a row on a page
  (`outreach/compliance.never_contact`): the names he gave (`ai/names.ALWAYS`),
  the ACU's and CPAC's own domains, any host with "cpac" in its name, and any
  event or organizer named after them. The scout never stores such an event
  (`agents/scout.store`, `outreach/research.vet`), the outreach agent never
  drafts for one and refuses one at the door even when approved, the hand add
  on the Outreach page refuses it, a follow-up is refused, and the do-not-contact
  page says so with nothing to remove. Pinned in `tests/test_outreach.py`
  (`NeverContacted`, `Pages`) and `tests/test_scout.py`.

## 2026-10-13: every failure is said once, and out loud

Chris's answers for the roadmap, 2026-10-13: optimize for less of his time,
more inquiries and bookings, reliability, visibility and self-healing ("I need
to also run the other parts of the business too"); polish what exists; small
room for spend. The first batch makes the suite's own silences impossible:

- The watchdog alerts each recorded error on its own (keyed by its row, not
  its kind), so a second error of the same kind inside six hours is never
  swallowed; it hears its own errors; an error is marked as sent only when the
  mail or the push really went, and a mail that could not go is itself an
  error (`alert_mail`). The inbox and the chief are watched for missed runs.
- A phone ping that did not go is an `ntfy` error on the Agents page, said
  once while it stands (`core/notify.py`, every caller passes its connection).
- Markers that lied: the Buffer numbers are marked pulled only after a pull;
  the morning brief is marked sent only when the mail went (the phone is told
  once a day either way; a failed mail is a `brief_mail` error and the hourly
  run tries again); a site outage no longer stops the inbox from sending the
  replies he approved (`site_pull`); the design samples are recorded as made
  only when `ccs design` finishes, so a failed run is tried again next hour;
  a failed site deploy is tried again after thirty minutes, three times per
  commit, and the status says "try 2 of 3".
- The draft page never breaks when the rewrite cannot run: it says so, records
  a `mend` error once, and the next run tries again.
- The brief's disconnected-channel line opens the Buffer page; More has an
  Errors page.

## 2026-10-13: tomorrow's post always lands

Batch 2 of the roadmap: the one post a day is never lost to a blip.

- An Anthropic error in the final check, the caption writer or the art
  director is a reason, not a dead run: the final check's failure is said
  once (`final_check`) and the photo skipped; the writer's failure leaves the
  template (`captions`); the art director's failure sends the draft to Chris
  not reviewed (`art_director`). A dead Drive sign-in is a no-draft morning
  like any other, said and tried again.
- The draft window: the 08:00 job fires once, so the hourly watchdog starts
  the content agent again between 08:00 and 20:00 while tomorrow has no
  draft, up to four runs a day, when the last reason was passing, the last
  run crashed, or the inputs changed (`content.inputs_fingerprint`); the
  same reason on the same inputs waits. The phone hears each reason once a
  day. Past 20:00 with no draft, a loud alert once. No plist changed.
- A draft for Tuesday goes out Tuesday: the day it was drafted for is the
  floor for every network's slot (`pacing.plan not_before`); a time Chris
  sets still wins.
- Every design carries the hero as a 2:3 card for Pinterest.
- The door rewrites a caption that breaks a rule now (the template in dry
  run, so nothing is spent) and checks again, instead of sending the post
  back for him to approve again; one rewritten within the hour that still
  breaks goes back with the reason. No connected channel and no open day
  are errors on the Agents page, said once.

## 2026-10-13: silence never posts, and his Approve is honoured

Batch 3 of the roadmap. Chris's choices for it, 2026-10-13: posts and replies
he approved in dry run go out when the lane is switched live; silence is one
nudge after eight hours, never a post set aside; the photos stay as they are.

- A reject sets the post aside with him on the record
  (`rule_report.rejected_by = "chris"`), its photo sits out for the repeat
  window like the art director's (`content.recent_use`; the event and the
  people are not "used", since nothing of it aired), and the content agent
  is started at once so the day is drafted again: tomorrow's post when it is
  missing, else today's when today's was the one set aside
  (`content.set_aside_for`). Reject asks first. A post that already went
  out cannot be rejected. Since 2026-10-15 it is Skip, and the photos of a
  skipped post go back into the rotation instead of sitting out (below).
- A draft waiting eight hours gets one push that opens it ("Still waiting:
  Tuesday's post. Nothing goes out unless you approve it."),
  `publisher.tend_drafts` on the ten-minute run; `rule_report.nudged_at`
  keeps it to one. It is never set aside, and the nudge goes whether the
  publisher is live or in dry run: the switch is about Buffer, the draft
  waiting for him is real either way.
- Switching a lane live (one, or everything at once) approves again what
  the dry run marked `would_publish` / `would_send`; the message says how
  many things go out. The publisher's door, `reply.ready_to_send` and
  `compliance.problems` check every one before it leaves. What was sent
  stays sent; back to dry run takes nothing back.
- A do-not-use entry sets the posts it touches aside
  (`rejected_by = "donotuse"`) with the reason and starts the content agent
  once, instead of leaving them in drafts for him to notice.
- An Approve can be taken back on the draft page ("Take back the
  approval") while the publisher has not picked the post up; a post Buffer
  already holds is pulled back from Buffer, not from here (roadmap 7.5).

## 2026-10-13: one tap on the phone

Batch 4 of the roadmap. Chris's choice for it: the morning ping carries the
rendered card and an Approve button; it ships on.

- Save is folded into Approve on the draft page, the quote reply and the
  organizer note: one form, two buttons ("Save", "Save and approve"). An
  edit is never lost on Approve; the gates (the suite's rewrite, the rules,
  the photos, the targets; `reply.ready_to_send`; `compliance.problems`)
  still hold on the way.
- Approve on the Queue list for a draft whose rules pass, photos are usable
  and art verdict is pass or not reviewed; a thumbnail opens the full card;
  the other captions unfold under it. Reject, Delete, Cancel, Exclude,
  Switch everything live, Remove and Spam ask first. Small buttons are 40 px
  tall.
- Approve from the ping (`core/approve_token`): the draft ping carries the
  card (`Attach`, fetched by the phone from the dashboard over Tailscale
  with the token, no login; nothing is copied to ntfy) and, when the art
  director passed the draft, an Approve button (an ntfy `http` action, a
  POST with a signed single-use token in its body) beside Open. The token
  is HMAC-SHA256 over the post id, its `updated_at`, an expiry (36 h) and a
  nonce kept in settings; a save or a rewrite kills it; a newer ping's
  token replaces an older one's; a GET on the address is a page with a
  button and approves nothing. The POST runs the page's own gates and
  answers in a sentence ("Approved post 7. It goes out Tuesday 11:30.").
  The eight-hour nudge carries the same.
- Words: the draft page never tells him to fix a caption; a photo approved
  by its folder says so instead of a no-op Undo.
- The Keys page holds every setting the code reads (posting times, the
  building day, the variety and repeat windows, the time zone, the brief
  hour, the Pinterest link, the scout region and horizon, the outreach
  caps), and a plain setting can be cleared back to its default. Secrets
  are replaced, never cleared from there.
- Google Drive sign-in from the phone: "Sign in to Google Drive" on the
  Drive page opens Google; the return page (127.0.0.1) does not load on the
  phone, so its address is pasted back on the Drive page. The same
  installed-app flow with PKCE as `bin/ccs drive login`, its state and
  verifier waiting in settings for 15 minutes; a foreign host, a stale
  sign-in and any scope but `drive.readonly` are refused. No Google console
  change.

## 2026-10-13: photos without the reload

Batch 5 of the roadmap: the Photos tab on the phone, in fewer taps, and the
site that follows them.

- A tap on Use, Don't use, Undo or Unblock answers in place (the page's own
  script asks for JSON; without it the form submits as before). Ticked
  photos take one tap: Use selected, Don't use selected.
- Exclude means out, fail closed: an excluded folder anywhere above a photo
  wins over a Use tapped on the photo, in the walker
  (`eligibility.clearance_of`), the one-pass map (`folder_decisions`,
  `decision_of`) and the Photos page's SQL. Don't use on the photo still
  wins over everything.
- A Blocked chip lists every photo marked Don't use, with Unblock; every
  card has Never use, which puts the photo on the do-not-use list and comes
  back to the same page.
- The site follows the photos: Use, Don't use, a folder decision, the hero
  pick and a do-not-use entry stamp `site.photos_changed_at`; ten minutes
  after the last change the updater's pass publishes by itself
  (`deploy.photos_pending`, inside `deploy.wanted`), with the same three
  tries half an hour apart as any deploy. The build holds the photos as of
  its start (`site.deployed_at`), so a tap during a build publishes again.
  Publish on the Website card starts it now instead of waiting.

## 2026-10-13: more bookings from the same site

Batch 6 of the roadmap. Chris's choices for it: the scout armed, around
Washington DC (DC, Maryland and Virginia); `chris@eventcaliber.com` on Google
Workspace ("I need a day to finish").

- The live Worker config follows the code: before every build
  `deploy.refresh_live_config` writes `wrangler.live.jsonc` from the
  committed `wrangler.jsonc` (read from git) with the booking database id the
  live file already holds; no id, no build. After every deploy the Worker's
  `NTFY_TOPIC` and `DASHBOARD_URL` secrets are put again from `.env`; a put
  that fails is an error on the Agents page, not a failed deploy.
- Pings end where he can act: the site's quote push opens the requests page
  (`Click`); a drafted reply pings once to its request (no name, email or
  phone in the push); drafted organizer notes ping once to Outreach; new
  scout finds ping once to Scout; a site that went live pings to the
  approved photos; design samples ping when ready.
- The scout is armed: `scout.dry_run` is switched off by migration 0070
  (one research call a week, about a dollar, inside the monthly cap); the
  region defaults to Washington DC, Maryland and Virginia when the Keys
  field is blank; "Search now" on the Scout page starts one run. Outreach
  stays as it was: it drafts, and a note leaves only on his Approve; that
  lane goes live only by his tap on the Agents page. The Outreach page
  shows the daily caps and the do-not-contact count.
- Mail is Google Workspace: `docs/SETUP.md` section 4 is the Workspace
  recipe (Google's DNS wizard for MX, SPF and DKIM; Email Routing off;
  `hello@` an alias if wanted; Keys, Mail = `smtp.gmail.com`, the address,
  a Google app password; Mail sent from = the address or a verified "Send
  mail as" alias). No code path changes; the proof is the test reply
  landing in his inbox once he finishes.

## 2026-10-13: see it: history, numbers, Today, the outside watch

Batch 7 of the roadmap.

- The live post's address rides with the history (`post_history.external_link`,
  migration 0071): the "posted" ping opens the post itself, and the Posts
  page links "Open on Instagram".
- A Posts page (a chip on Today): what went out, where it lives, the reach,
  engagement and clicks Buffer gives, the last 30 days and the last 12 weeks
  in plain tables (`buffer/metrics.summary`, `trend`, written for this and
  shown nowhere until now).
- Today says what needs him before the morning brief exists: `chief.needs`
  is the plain SQL half of the brief, shown at the top of the Queue page
  with the open-error count linking to the Agents page.
- The outside watch, free: the Mini checks in with the site hourly
  (`watchdog.check_heartbeat`, `POST /api/heartbeat`); the Worker's cron,
  every 30 minutes (`wrangler.jsonc` `triggers.crons`, on the Workers Free
  plan: five per account, read from developers.cloudflare.com on
  2026-10-13), rings the phone once, urgent, when two hours pass without a
  heartbeat, says "back" once when one returns, and says nothing while no
  heartbeat was ever posted. "Test the outside watch" on the Keys page asks
  the site to send that ping now, marked as a test. The one watch that does
  not live on the Mini.
- A scheduled post can be pulled back from Buffer ("Pull back from Buffer"
  on the draft page): deleted there one network at a time
  (`BufferClient.delete_post`, the mutation's input read from the live
  schema), then a draft again; what Buffer keeps stays scheduled, with the
  reason on the Agents page.

## 2026-10-13: leftovers

Batch 8 of the roadmap, the last one.

- A red update leaves the venv as it was (`agents/updater.update`): new
  requirements are installed before the tests, so when the tests fail on the
  Mini the checkout's own `requirements.txt` is installed again and the line
  says "requirements put back". A put-back that fails is an error on the
  Agents page (`update_requirements`) naming both commits, never a silent
  venv on the wrong code.
- Every paid Anthropic call holds its place on the ledger while it is in
  flight (`ai/spend.reserve`, `release`, `record(..., reservation=)`):
  the caption writer, the art director, the final check and the scout's
  research each reserve before the call (USD 0.15; the research call USD
  0.75), the reservation becomes the real row when the call settles, is
  released when the call fails, and is swept after 30 minutes when the
  process died. A reservation that would pass the monthly cap means no call,
  said as the cap is said (the final check records `ai_cap`; the scout's
  line says "would be passed by another research call"). Two agents can no
  longer each overshoot the cap by one call.
- Calendar attending/official stays out of the posts: no official events
  exist, and wiring it is the one way a caption could claim an affiliation
  (the affiliation rule above).

## 2026-10-13, evening: the Search Console value is taken in every form Google gives, and said when it is not

Chris: "It says Google search console tag is missing?" over a filled Keys
field. The build kept only the HTML tag or its content value and dropped
anything else without a word, so the Website card said "missing" and nothing
said why.

- `site/build.parse_verification` takes every form Search Console shows: the
  HTML tag, its content value, the TXT record of a Domain property
  (`google-site-verification=...`) and the HTML file's name or content; the
  file method writes its file at the root of the site.
- A value that is none of these is refused on the Keys page with the reason,
  shown on the Website card as "unusable" with the reason, and recorded once
  on the Agents page by a live build (`verification_tag`). Never a silent
  blank.
- A saved Search Console value makes the site republish itself ten minutes
  later, like a photo change (`site.tag_changed_at`); no Publish tap.
- The check from outside after every publish looks for the tag on every live
  page (or the file at the root), where Search Console looks; a page without
  it fails the publish and the card says so.
- A property Search Console verified by itself (Chris: "it never asked for a
  html tag for ownership when I verified"; a Domain property through
  Cloudflare's DNS) needs nothing on the Keys page: the card says so in plain
  words, with no badge. An empty field is not a fault.

## 2026-10-14: his brothers' galleries

Chris: "Can you pick up shared galleries too on drive? Several have me and
my brothers images." They live under "Shared with me" (his brother's own
Drive, shared to the account); every shared folder with photos is taken in.

- Drive lists only what was shared directly, so the scanner now walks each
  shared gallery for the photos inside it (`drive/scan.walk_shared`,
  `DriveReader.children`), in the weekly full pass and, for a gallery shared
  since the last run, within the hour (`incremental` lists the shares again).
  Reads only, before any transaction opens; the scope stays `drive.readonly`.
- A shared gallery is a top folder of its own, "Shared with me/<name>",
  cleared like any folder; a folder shared on its own inside a gallery he
  can see keeps its place under it, so clearing the gallery reaches it. A
  single photo shared on its own has no folder and is cleared only by hand.
- Nothing in a shared gallery is used until he clears the folder or the
  photo; an excluded gallery keeps its photos out. The same law as his own.
- Who shared it is kept as a name (`drive_folders.shared_by`), shown on the
  Folders list, the folder page and the Drive page. No address is asked for
  or stored.
- In passing: a photo loose at the top of My Drive no longer gets a "(new
  folder)" stub row on a changes run (the root ids are remembered).

## 2026-10-14: no picture follows the mouse

Chris, on the site from his computer: "It just follows my mouse (that
picture)." The coverage peek (a photo that trailed the cursor while the
mouse was over the Coverage list) is removed from the home page, its style
and its script. The cursor ring and the hero's web are the only things that
answer the pointer; nothing else on the site moves with the mouse.

## 2026-10-14: every approved photo gets its turn

Chris: "You also keep using the same fucking photos for everything when I
have approved at least 40 by now." Every picker ranked the approved pool by
the same score and took the top of it: the daily draft (held back only by
the repeat window), the website's grid and venues, the design samples. The
strongest few therefore won on every surface, and a newly approved photo
below them was never seen.

- The rule: with N approved photos, every surface uses all N before any
  comes round again. Each picker draws the least recently used photo first,
  on any surface (a photo in yesterday's post is at the back of the line
  for tonight's site build too), and the quality order only breaks ties.
  Quality never decides on its own.
- The memory is one table, `photo_use` (photo, surface, which post, build
  or samples folder, when), written where a surface commits to a photo:
  every draft (a dry-run draft too, since one approved in dry run goes out
  when the lane is switched live; the art director's turned-back draft too,
  it sat out before), every site build that is not a preview, every set of
  samples. The drafts made before the table existed were filled in from the
  queue once, so the day this landed the site and the samples already
  preferred what no post had shown.
- The repeat window (`PHOTO_REPEAT_DAYS`, Keys page) stays as the floor: a
  photo on a draft sits out for the window whatever the rotation says. With
  about 40 approved photos and a 180-day window the drafts run dry in a few
  weeks; the rotation makes a shorter window safe, and the window is his to
  set.
- The hero he picked or sent is never rotated away. The grid and the venues
  under it rotate on every publish.
- The samples are made again when the approved photos change (one
  approved, one taken away) or the words on the cards do, never because
  the six they would draw rotated (that would remake them every hour).
- A draft set aside because he corrected a shot word gives its photos back
  (the same photo leads the new draft, with the right words).
- The Photos page, Approved, says under each photo "used N times, last on
  <date> (post, site, samples)" or "never used yet"; the content run's line
  on the Agents page says which photo led and why ("never used before; 40
  ready, least recently used first").

## 2026-10-14: a photo from the phone becomes a draft post

Chris: "if I'm in the middle of shooting conventions and want to share a
photo I took from my phone can we set up a way to send the photos to the
suite for social upload?" His answers: a draft post right away, from a page
on the dashboard.

- The Send a photo page (Today) takes one picture from the camera roll or
  the camera and one optional line about it (what the room was; a line that
  names a known event or person is refused). JPEG, PNG and HEIC.
- The picture is kept on the Mini as the photo's own file (DATA_ROOT/phone,
  re-encoded from its pixels: no camera data, no GPS), never written to
  Drive. It is a cleared photo of its own ("From the phone" on the Folders
  page): his own photo, sent by him, for his own post. The weekly Drive pass
  never marks it trashed; the nightly sweep never deletes its file.
- The phone agent drafts it at once, the way the daily draft is made: the
  sorter, Claude's final check (someone who may be under 18, a readable
  plate, a wedding stop it, and the page and the Agents page say why), the
  captions with his line as a fact, the single design, the art director,
  the ping with the card and Approve. Nothing posts without his Approve.
- Approved, it goes out as soon as Buffer takes it (about 35 minutes after
  his Approve), never at the day's usual slot (`rule_report.asap`).
- A send while one is being drafted waits its turn (`ccs run --wait`),
  never lost. The lane follows the content lane's dry-run switch: in dry
  run the page says Claude did not look and the draft cannot post.
- The first phone send's ping is the show for this surface.

## 2026-10-15: Post this on a design sample

Chris: "Put a "Post this" on every design sample so I can turn a sample I like into a real draft post." The
samples were for review only and had no road to Buffer; the only road was the daily draft.

- The rule: **Post this takes the same road and the same gates as the daily draft.** Never a shortcut.
- Every sample on the samples page (the fan, the spotlight, the carousel and the reel) has a Post this. The
  samples record (`about.json` `samples`, written by `render/design_samples.make`) keeps each sample's design
  and the photo ids it was made from, the hero first.
- The press is recorded (`sample_posts`) and the sample agent drafts it (`agents/sample.py`, `ccs run sample
  --wait`: a press while one is being drafted waits its turn). The same photos are fetched again at full size;
  Claude's final check looks at every one (someone who may be under 18, a readable plate, a wedding), and one
  that fails drops the whole draft, with the photo and the reason said on the samples page and the Agents page.
  Then eligibility, the captions through the same writer and copy rules, the same renderer with the same design
  (the reel with the current music track, the carousel when the reel fails), the art director, a queue row and
  the ping with Approve (`content.make_draft`, the daily draft's own end). The photos' use is recorded for the
  rotation.
- The draft is for today and goes out as soon as Buffer takes it after his Approve (`rule_report.asap`, as a
  photo from the phone). Nothing posts without his Approve.
- A sample whose folder was made again since, or with a photo no longer approved, says so plainly on the page
  and makes no draft. A reel with no music track says so too: a reel never goes out silent (2026-10-11).
- The lane follows the content lane's dry-run switch. In dry run nothing is drafted and the page says why: the
  final check is a paid look, and a sample is never drafted without it.

## 2026-10-15: Post to Event Caliber, his send is his approval

Chris: "i want to be able to text an image from a current event im doing to
the dashboard to auto post immediately. right now you have to be on the
dashboard to do that and thats a pain". His answers: a share sheet button on
the iPhone (in Photos, Share, "Post to Event Caliber", an optional line),
sent through eventcaliber.com with no dashboard and no Tailscale; and post
right away.

- **A photo he sends from the share sheet is approved by the act of sending.**
  It is the one exception to "nothing publishes without Chris's Approve on
  the dashboard" (standing rules, below). A photo sent from the Send a photo
  page still waits for his Approve, as on 2026-10-14.
- The road: the Shortcut posts the photo and the line to
  `eventcaliber.com/api/send` with the send token in its Authorization header
  (`SEND_TOKEN`, made on the Keys page, put on the Worker by every deploy).
  The Worker refuses anything without that token, anything that is not a
  JPEG, PNG or HEIC by its own bytes, anything over 40 MB, more than twenty an
  hour and more than thirty waiting; it keeps the photo under
  `private/sends/` in the company's R2 bucket, which `/m/` never serves, and
  answers "Received." The Mini pulls with its own token every minute
  (`launchd` `phone`, `--when-waiting`; the inbox's ten-minute run starts it
  too), keeps each one like a send from the page (re-encoded, no camera data,
  no GPS, never in Drive), deletes it at the site, and drafts it on the same
  road: the sorter, Claude's final check, the captions with his line, the
  single design, the art director.
- What still stops it, and the phone hears why each time: a file that is not a
  photo or is too small; a line that names an event or a person; Claude's
  final check (a readable plate, house number, street sign, screen or
  document; a wedding or a private occasion; every other eligibility rule);
  the art director turning it back, or not able to look (then it waits for
  his Approve); the publisher's door (a caption that still breaks a rule
  after one rewrite, a photo no longer usable, a repeat). In the content
  lane's dry run Claude does not look, so nothing is approved and the ping
  says what it would have posted; in the publisher's dry run it is approved
  but nothing goes out, and the ping says when it would have.
- Approved, it posts right away. Asked whether to keep the 35 minutes the
  asap rule leaves to pull it back, Chris chose "Right away": it goes to
  Buffer to post now (`shareNow`, `publisher.posts_now`), with no pre-post
  window, and the publisher is started at once; a time he sets on the draft
  still wins. The ping says it is going out now; when Buffer reports it sent,
  the next ping opens it on Instagram, where he can delete it, with the
  dashboard beside it. The daily draft, Post this and the Send page keep
  their windows.
- Only Chris can do: press Make a send token on the Keys page and copy it into
  the Shortcut; build the Shortcut (docs/SETUP.md, section 10a); run
  `scripts/go-live.sh` once on the Mini for the one-minute pickup (until then
  the inbox's ten-minute run picks the photos up).


## 2026-10-15: his photographers send too; every instant photo is a Story

Chris: "What if I have several photographers that I want to be able to share
photos instantly?" His choices: a team member's photo comes to him as a ping
with one tap ("Ping me, one tap"); every instant photo goes out as an
Instagram Story, and he can promote the best to the feed ("Both"); "Up to 10
Stories, 2 feed posts" a day across everyone. And: "Does every photographer
need a shortcut on their phone": one Shortcut he shares as an iCloud link,
and a private upload page for a phone without Shortcuts.

- **A photo from his photographers is approved for use by his Approve.** It
  is checked exactly like his own (Claude's final check, the art director,
  the captions' rules, the publisher's door), then comes to him with the
  card, Approve and Skip. Approved, it goes out as a Story right away. His
  own sends keep posting right away, approved by his send, as Stories now.
- Everything a photographer reads (the upload page, the Shortcut's answer,
  the setup steps) says "Chris or Nic approves it before it goes out". Chris:
  "It's always the both of us." Nic is not set up as an approver yet; that
  comes when Chris sets him up.
- **A photographer is never named in public, and never in a ping.** Their
  first name is kept on the Mini only and shown to Chris only (the Team page,
  the Send page); ntfy topics are not private, so a ping says "a photo from
  your team". The site holds numbers and token hashes, never a name.
- The Team page (Settings, beside Keys): add a photographer by first name;
  each gets a send token of their own, shown once and kept only as its
  SHA-256; each can be switched off, which the site honours at once; a new
  token or a one-time phone link (7 days, works once) is shown once. The
  team list reaches the site the moment it changes (`PUT /api/team`), with no
  redeploy; until it does, a new token does not work there.
- Every instant photo is an Instagram Story: a 1080 by 1920 card with the
  photo whole, the mark and the address, no caption (`motion.story_card`,
  Buffer's instagram type `story`). The ping and the draft page offer "Also
  post to the feed", which makes a feed post of the same photo with its
  captions and 4:5 card, approved by that press, posted right away.
- The cap: at most 10 Stories and 2 feed posts a day from instant photos,
  everyone together (`agents/team.py`). Past it a photo waits on the
  dashboard with the plain line and the ping says so; the publisher holds
  the cap too.
- A phone without Shortcuts: the one-time link opens a page with one button
  (a link preview uses nothing); the button sets an HttpOnly, Secure,
  SameSite=Strict cookie of its own and opens the upload page
  (eventcaliber.com/upload: one photo, a line, Send), which saves to the
  home screen. The token never travels in an address; the page sends only
  from the site's own origin.
- Only Chris can do: add the photographers on the Team page; make the
  shareable Shortcut once and share its iCloud link (docs/SETUP.md 10b).
## 2026-10-14: the website for three sizes

Chris, on the site: About needs a real place in the navigation; the words over
the hero photo are unreadable; a general Contact page is missing; the gallery
says Scroll but moves sideways when you scroll down, and should roll on its
own at a slow pace; the footer is nearly empty; what does a Google search show.
His rule, verbatim: **"we must ALWAYS treat UX UI optimization for phone ipad
and computer, no shortcuts!!!"** His decisions when asked: a bottom bar on
phones; a phone number on the site, added on the Keys page (nothing shows
until he does); one page per coverage item; the Contact page is email and
phone only, no form. From the local search playbook he showed: one page per
service with the place in its title, a complete business block, a plain first
sentence on every page, a tappable number on phones, Bing. Not taken: law and
medical specifics, review platforms, link buying, town-by-town pages, FAQ rich
results.

- **Three sizes, every page** (`site/theme.py`, pinned by
  `tests/test_site_sizes.py`). Phone to 760px: the bar at the bottom, always
  visible (Work, About, Contact, Quote), clear of the iPhone's home indicator,
  the page padded so nothing ends under it; at the top the logo, the number
  when set, and Quote. iPad 761 to 1100px: the menu in words and the quote
  button at the top; the number in the footer and on Contact. Computer above
  1100px: the words, the number and the button. Touch targets 44px or more;
  the pointer ring only for a fine pointer. Checked as iPhone 390x844, iPad
  820x1180 and 1180x820, computer 1440x900 (a landscape iPad gets the
  computer's layout).
- **The menu is words** (Work, Coverage, About, Availability, Contact), the
  page you are on marked; Work is in the words only while the home page has
  the strip, and goes to the coverage pages from the footer and the bar
  otherwise (`theme.shell`, `_current`).
- **The hero's words sit under the photo** on a solid band: the kicker, the
  headline, a plain first sentence, the lede and the quote button. Nothing is
  written over the picture; the photo keeps the brightness, saturation and
  dodge of 2026-10-12, the web and the corner marks. The headline ends above
  the fold at all four sizes.
- **The work strip rolls on its own**, 24px a second, pauses under the
  pointer, a finger or keyboard focus and while the tab is hidden, moves one
  frame per arrow, stays still under reduced motion, and never moves with the
  page's scroll (a native sideways strip, the frames doubled so it loops).
  The old scroll-driven reel and the timecode are gone.
- **"the horizontal images must not be cropped anywhere on any device or
  should at least open to the full image - the landing page photo i know
  needs to be cropped at times"** (Chris, 2026-10-14, later the same day).
  Every frame on the site has its photo's own shape (`build.aspect`, the
  `--ar` the build writes on each frame) and shows it whole: the work strip
  (a wide photo is wide, a tall one tall, the strip's frames differ in width
  and bottoms line up), the delivery stack, the venues (the parallax that
  needed a taller picture to slide is gone), the coverage pages and the About
  page (a column layout, each picture whole). The hero is the one picture
  that may be cropped, and the only `object-fit:cover` on the site.
- **"the website gallery has duplicate images and lets expand the gallery to
  more images and a variety"** (Chris, 2026-10-14, on the live site). The six
  live frames were six different pictures (no two alike by bytes or by
  perceptual hash); what read as duplicates were the loop's copies coming
  round after only six frames, and four of the six were portraits. Now the
  strip is twelve frames (`build.COVERAGE_ROWS`), drawn across the rooms and
  the events (`build.pick_grid`: one of each kind of shot before any repeats,
  one event per round before any event repeats, the least recently used first
  within a room), never the same photo twice and never the hero; the loop's
  copies are dropped by the page's script when the photos themselves fit the
  screen, and then nothing rolls. The rooms rule is a variety rule like the
  events rule of 2026-10-11: a room with few photos comes round before every
  photo of a big room has had its turn. His follow-up, "same picked twice":
  the library holds the same picture under several ids (the same file in two
  Drive folders; 1,431 md5 groups, 27 of them among cleared photos, that
  day), each with its own sorting, so an id check passes and the picture can
  come twice. One row now stands for each md5 group on the site
  (`build.one_per_picture`), its use under any id counts for the whole group,
  and his own hero pick on a twin is still his pick. Both builds that reached
  the live site that day had shown seven distinct pictures; the repeats he saw
  were the loop's copies and two portraits on one backdrop.
- **"the top website scroller cuts off on the left side when viewing on a
  computer. who we are - should be more than two fucking words! dont just
  skip the small stuuf becuse thats just as important as the main page"**
  (Chris, 2026-10-14, on the live site from his computer). The rule: the
  small stuff on every inner page gets the same care as the home page, at the
  three sizes. The ticker under the hero fades out over the page's gutter at
  both ends (`theme.CSS .ticker`, a mask over `var(--pad)`): the word leaving
  at the left was sliced flat at the screen's edge while everything else sits
  behind the gutter. The Privacy page's "Who we are" was one line ("Event
  Caliber is a brand of CKI, LLC."); it says who the two of them are, where
  they are based and the company behind the brand (`copy_text` `who_we_are`).
  From a pass over the sixteen live pages at the four sizes the same day: the
  Contact page's email address broke mid-word in its box on an iPad and a
  computer (the links are 16 to 24px now, the boxes a little wider); the
  Thanks and Not-found pages were a headline and a button over an empty band
  (each says what happens or where to go, in a sentence, and inner pages end
  closer to the footer); the quote form's Kind of event menu cut its first
  choice short in a half-width field (full width now).
- **One page per coverage item** (`/coverage/<key>/`, nine of them, and the
  coverage index): the title with the place ("Backstage event photography,
  Washington, DC | Event Caliber"), a plain first sentence, a paragraph, up to
  six photos of that room (`build.pick_page_photos`: the room's own kind of
  shot first, each photo on one page before any page repeats one, a thin
  room filled from the rest of the pool), the Service, BreadcrumbList and
  ImageObject blocks, the other eight pages under it. The words are Chris's
  in `offer.json` (`title`, `first`, `about` on each item) and pass the copy
  rules at build. A title over 75 or a description over 160 characters stops
  the build, said, never cut (`build.TITLE_MAX`, `DESCRIPTION_MAX`).
- **The rotation and the coverage pages.** Every usable event photo is on some
  coverage page on every build (six a room, least recently used first). What
  a build records in `photo_use` is the home page's own photos (the hero when
  it is a library photo, the grid, the venues): a coverage page is a view of
  the whole library, not a pick, and recording it would put every approved
  photo on the same footing after each build, so the home page would stop
  rotating. The Photos page's "used N times" therefore counts posts, samples
  and the home page, not the coverage pages.
- **Contact** (`/contact/`): email, the phone number when set, the area line,
  the privacy link, the quote button; no form. The number is tappable on the
  page, at the top on phones, in the footer and in the business block.
- **The footer** on every page: the company and where it works, the nine
  coverage links, the pages, the email, the number and the social addresses
  when set (https only), and the legal line with the year.
- **Search:** the sitemap, IndexNow and the outside check read one list of
  sixteen public pages (`offer.public_pages`); every page has og:url,
  og:site_name and a Twitter card; a coverage page's og:image is its first
  photo; the thank-you and not-found pages carry noindex and no canonical;
  the business block says areaServed (DC, Maryland, Virginia, United States),
  a locality and region and never a street, the image, the logo, the telephone
  when set and sameAs from the socials; the About page has a Person block for
  each brother; www. answers 301 to the apex (`worker/index.js`; the
  Worker runs before the static assets, `run_worker_first` in
  `wrangler.jsonc`, or a www page is served from the assets and the
  redirect never runs, as the live site showed after the merge).
- **The Keys page, Website contact** (`BRAND_PHONE`, `SOCIAL_INSTAGRAM`,
  `SOCIAL_FACEBOOK`, `SOCIAL_PINTEREST`): blank hides each; a save stamps
  `site.keys_changed_at` and the site republishes itself within minutes like
  a photo change (`deploy.SITE_KEYS`, `KEYS_CHANGED_KEY`). A change to the
  search markup, the photo text or the offer module redeploys the site too
  (`deploy.SITE_PATHS`).
- Only Chris can do: the number and the social addresses on the Keys page; a
  Google Business Profile for Event Caliber as a service-area business (the
  nearest photographer category, service areas DC, Maryland and Virginia, the
  same name, phone and email as the site) and Bing Places; a photo of the two
  of them for the About page, if he wants one there.

## 2026-10-15: no age gate; his Approve is the check

Chris: "Stop with this 18 and under bullshit! It stops damn near half the
images from posting and its wildly incorrect. Get rid of the gate all
together! If I approve something, it means I checked it and you are not
required!"

- No model is asked whether anyone could be under 18 (the sorter and Claude's
  final check), and an answer written before the ruling stops nothing: not
  eligibility, not the Photos page's review list, not the best frames, not
  Post this, not a photo from the phone, not the design samples or the site.
  The Photos page and the library report no longer count anyone "set aside".
- What still stops a photo, exactly as before: not cleared, Don't use, an
  excluded folder, the do-not-use list, no consent in the credits sheet, not
  sorted by a model yet, a readable plate, house number, street sign, screen
  or document, a wedding or a private occasion, a costume photo, a building
  rule, no final check yet, and his Approve on every post.
- The `possible_minor` columns stay in the database (no migration); nothing
  reads them.

## 2026-10-15: Instagram only, for now

Chris: "we are ONLY using Insta now so get rid of the other socails or tunr
off thier errors for now". The Buffer account has only the eventcaliber
Instagram channel in Use.

- Posts go to the networks named on the Keys page (Posting: "Networks posts go
  to", `POST_NETWORKS`, comma separated). Blank is Instagram only.
- A network that is off is never sent to and never reported as missing a
  channel: no more "Not sent to facebook (no connected Buffer channel)"
  alerts. Facebook and Pinterest come back by adding them to that field once
  their channel is connected and in Use.

## 2026-10-15: the logos of the organizations he has photographed for

Chris: "should we add the companies we have worked for on the website? like
their logos and say we have worked with them?", then "it can be political
organizations, i just dont want them the only thing on the site". His answers
when asked: under the top photo on the home page; each logo in its own
colours; headed "We've photographed for"; no permission from the
organizations needed (his call: a logo is the organization's trademark and
some contracts forbid showing it; he was told).

- The one exception to "never which event, never who" (2026-10-11): the
  organizations he lists may be named, by their logo and its label, in this
  strip on the home page and nowhere else. Captions, the words on the posts,
  the photo text and the search fields still name no one (`ai/names.py`,
  `ai/copy_rules.py` rule `names`, unchanged).
- The list is `offer.json` `clients` (name, logo file under `site/clients/`,
  `spread`, `tile`, and where the logo came from and when: `source`,
  `fetched`), on and off by `show`; the heading passes the copy rules at build
  (`site/clients.py`). `spread` marks a political organization; offer.json and
  `site/build.py` still never say the word (2026-10-12, pinned).
- His list, as he gave it and corrected it through the coordinating session:
  Library of Congress, Hamel Builders (one logo; "Hamel Commercial" is the same
  company), C.A.S.E. (the Center for Adoption Support and Education,
  adoptionsupport.org, not case.org), Washington Nationals, American Heart
  Association (the file he sent), Associated Press, ACU (the older American
  Conservative Union mark, from conservative.org as archived on 2018-12-22),
  CPAC, WC Smith, Bozzuto, APTA Pelvic Health (the former Women's Health
  section, its current logo), Grimm + Parker Architects. Every other logo was
  taken from the organization's own site. Waiting on his file: Miner Feinstein
  Architects ("MF Architects", Frederick, MD; "yes thats the company"), which
  has no website. Not on it: Absolute Love Adoptions ("dont add absolute
  love").
- Politics fail closed: a logo counts as political unless its entry says
  `spread: false`. Political logos never outnumber the others; a
  non-political logo comes first and the political ones are spread evenly
  through the row, never side by side; one past the count waits for another
  non-political logo, said on the Agents page.
- Each logo sits on a white tile (a dark one for a logo drawn in white),
  trimmed to what shows on its tile, sized by its weight rather than one
  height (a long wordmark comes down, a square mark goes up), re-encoded from
  its pixels (no metadata travels); an SVG with a script or a link to
  elsewhere is refused. The strip wraps at the three sizes (pinned by
  `tests/test_client_logos.py`).
- On since his word on the renders at the three sizes: "On, rows centered
  (Recommended)". Every row of the strip is centred, the short last row under
  the full ones, the heading over them. (The tiles and the rows gave way to a
  scroller on 2026-10-16, below.)

## 2026-10-15: the ACU and CPAC on the logo strip, never in outreach

Chris: "no you can use acu and cpac for this, i just donrt want them emailed
for outreach as i stated in the beginning". Their logos may be on the "We've
photographed for" strip (both marked political, so they never lead and never
outnumber the others). The rule of 2026-10-13 is untouched: CPAC, the ACU and
their affiliates are never contacted (`outreach/compliance.never_contact`, the
scout, the outreach agent, `ai/names.ALWAYS`). Pinned both ways in
`tests/test_client_logos.py`.

## 2026-10-15: four new designs, colour from the photo, and the week

Chris: "could you also come up with some new designs (like 4 so they arent
all exactly the same design everytime) and make sure you follow strict color
theory and proper design and make them super super super dynamic and punchy".
On the first renders: "i like the design of 7,8,9 and 10 and create one more
thats radically different with a new technique use". On round 2, through the
coordinating session: "perfect! and we still keep the original one we started
with on the very first post to insta".

- **The four** (`render/bold.py`), each the same design at 4:5 and as its own
  2:3 card: the **poster** (the room's name stacked to the full width on
  paper, the photo under it, black and white as he picked), the **slit scan**
  (the new technique: the photo whole, its most colourful line of pixels drawn
  out into light streaks above and below it, the words on black tape), the
  **cascade** (three photos stepping down the frame, the hero last and
  largest, a band of colour behind) and the **select** (the hero large over a
  contact strip of the set, the pick boxed). The colour field design of the
  first round was dropped.
- **Kept:** the **spotlight**, the design of the very first post that went to
  Instagram (queue post 2, Buffer 6ad00a04117064a577d1469f, drafted for Monday
  2026-10-12).
- **Every photo whole**, its own shape, never cropped or covered, and no word
  is set over a photo (the 2026-10-14 ruling on horizontals, kept on these
  posts).
- **Colour** (`render/palette.py`): the brand's black, greys, white and cyan,
  plus one accent taken from the photos: their colours found by k-means in
  OKLab, the photo's hue the colour with the most weight times chroma, turned
  by the design's rule (cascade split complementary, select triadic, each the
  side farthest from the photos' other colours and the brand cyan), at the
  design's lightness and the most chroma sRGB shows. A photo with no hue takes
  the cyan; an accent that would be muddy is not used. The poster and the
  slit scan add no colour of their own (the slit scan's streaks are the
  photo's own pixels).
- **Contrast is checked before anything is drawn**: every word against the flat
  colour under it, 4.5 to 1 for small type and 3 to 1 for large (64 px and up
  on a 1080 px post). A palette that fails is drawn in the brand's black and
  white. A word that would leave the frame, or a letter a brand face lacks
  (Michroma has no arrows), is refused.
- **The week** (`agents/content.py` `DESIGNS`): Monday spotlight, Tuesday
  poster, Wednesday slit scan (the building day too), Thursday cascade, Friday
  select, Saturday the reel when a music track is on, Sunday poster; no design
  two days running. A day with too few photos that pass the final check, a
  building photo on a day of several, and a Saturday with no track take the
  one-photo design neither neighbour uses (`fallback_for`). The single, the
  carousel and the fan leave the week; a phone send, a Post this on a sample
  and a reel that cannot be made still use them.
- **A room is named only when Claude's final check of the full photo confirms
  it.** The first renders put "After Dark" on a sunny garden and "Main Stage"
  on a reception room, from the sorter's shot type. The final check now also
  answers which room the photo plainly shows (main stage, backstage,
  portraits, expo floor, after dark, the crowd, the venue) or none
  (`library/classify.py` `ROOMS`, `final_checks.room`, migration 0077); a post
  prints that room's words (`render/design_samples.ROOM_WORDS`) or EVENT
  PHOTOGRAPHY, with EVENT CALIBER as the small line so it never repeats. This
  holds for every design that prints a room, the spotlight and the reel
  included; a dry-run draft and a photo checked before 2026-10-15 name no room.
- Pinned by `tests/test_bold_designs.py`.

## 2026-10-15: the doctor fixes what it knows, and files what it does not

Chris: "a doctor agent too to auto fix anything that fails realtime." On
2026-10-14 the watchdog said "The newest database backup is 4d 0h old": the
backup and the nightly sweep had not run for four days, the alert went out,
and nothing fixed it. The watchdog finds; the doctor fixes. The scope, set
with him the same day:

- **It fixes the known failures by itself**, every five minutes, on its own
  service (`agents/doctor.py`). An agent whose run failed or is overdue is run
  again. The backup overdue, or its file stale, runs now, and the sweep runs
  inside it. Disk under the watchdog's threshold runs the sweep. The dashboard
  not answering on localhost is restarted: only the process proven to be this
  suite's dashboard is stopped, and launchd's KeepAlive on its own label starts
  it again. A post that failed for a passing reason (a Buffer timeout, a 5xx, a
  rate limit) goes back to the publisher for its next slot, his Approve
  standing; never one that reached Buffer on any network. A reel that failed to
  render is remade on its draft, never without a track. The content agent is
  left to the watchdog's draft window (2026-10-13). A Drive sign-in that
  expired cannot be fixed by code: his phone gets the link to sign in, once a
  day. At most two agents are started a pass: after a reboot every agent
  looks overdue at once, and the Mini's memory is shared by three suites.
- **It checks each fix.** After a remedy it reads the same signal again and
  records fixed or not fixed (`doctor_remedies`, migration 0076). Never a
  loop: at most three tries per problem per day, the second after 30 minutes,
  the third after two hours. A remedy that did not work is said to Chris once,
  with what it tried; one that cannot run at all is said once, at once. A fix
  is a quiet ping. The digest and the morning brief carry one line per problem
  per day (Chris, on the examples: "one digest line per problem per day"): the
  last try's outcome, with how many tries and when.
- **For a bug in the code it never edits live code**, because a bad self-fix
  at 3am breaks production. An exception in our code becomes one GitHub issue
  per distinct error (the agent, the kind and the traceback's frames make it
  one) in ChrisKennedyImages/cki-convention-social, with the traceback, the
  agent, the time and the last log lines, every secret taken out. His phone
  gets the link; the fix comes as a pull request. A repeat is
  counted on the same issue; one that comes back after he closed the issue is
  filed again. The token is `GITHUB_TOKEN` on the Keys page (fine-grained, this
  repository, Issues only); without it the doctor pings instead.
- **What it never does:** edit code, run git on the Mini's checkout, stop or
  restart anything that is not ours (no other suite's label, process or port),
  or touch a file outside the data root (the sweep deletes, inside it only).
  Pinned by `tests/test_doctor.py`.
- It starts in dry run, saying what it would do at the cadence it would do it;
  Chris switches it live on the Agents page. The watchdog watches it: a doctor
  silent for 30 minutes is a missed run.
- Its service file is new: `scripts/go-live.sh` runs once on the Mini to
  install it (the updater flags it on the Agents page).

## 2026-10-15: one Today page; designed drafts come to the phone

Chris: "we really need to fix this dashboard. its very difficult to understand the UX and UI. design samples is
completely in a different place then todays posts and today has no sign of design examples. why are they examples?
cant they just create them and send them to ntfy for me to approve and watch? everything is just very confusing".
Asked which of four changes to make, he chose all four; up to 3 designed drafts a day; on Approve "an option to post
immediately or to follow the pace"; Skip puts the photos back in rotation. Then: "we keep reusing the same photos too."

- **Designed drafts, no more samples page.** From 8:00 to 20:00 the hourly scanner starts the designed lane
  (`agents/designed.py`) while today has fewer than `DESIGNED_PER_DAY` designed drafts (Keys page, Designed drafts;
  default 3, 0 stops them, 6 at most) and fewer than that many still wait for him: one an hour, and none pile up
  while he has not answered. Each is a real draft on the daily draft's road and gates, never a shortcut: approved
  candidates only, Claude's final check on every photo (one that fails is passed over), the captions through the
  same writer and copy rules, the same renderer, the art director, a queue row for today, the photos' use recorded.
  The design is the one the designed drafts used least lately, read from the renderer's own list (`content.NEEDS`:
  a design added there joins by itself), the reel only with a music track. The lane follows the content lane's
  dry-run switch: in practice run nothing is made. The samples are no longer made every hour; their page and the
  Design card answer with Today. A designed draft is never chased by the eight-hour nudge.
- **His three choices, everywhere a draft waits.** Post now (posted at once, "post immediately": Buffer's shareNow with
  no time, the share sheet's path, and the publisher started there and then; `rule_report.approved_how`), Follow the pace (the next open Instagram slot, one post a slot; a photo from the phone too)
  and Skip. They are on Today, on the draft page (the edit form's own buttons, so an edit is never lost) and on
  every draft's ping: the card (a reel's own cover), a tap that opens the draft where the reel plays with its sound,
  and the three as ntfy actions with one signed single-use token (`core/notify.choice_actions`,
  `POST /queue/<id>/choose-by-token/<now|pace|skip>`; a GET decides nothing). A draft the art director did not pass
  pings with Open and Skip. Nothing posts without one of his two approve choices.
- **Skip** sets the draft aside with him on the record (`rejected_by = "skip"`) and its photos go back into the
  rotation, never Don't use: `content.recent_use` leaves a skipped post out, and its use stays on the rotation's
  record, so the photos come round again after the others. A skipped daily post is drafted again at once; a
  skipped designed draft is not replaced. This replaces Reject (2026-10-13), whose photos sat out the window.
- **Variety.** No photo goes out twice inside the longer of `PHOTO_REPEAT_DAYS` and `VARIETY_DAYS`
  (`config.repeat_window`), by any road: the publisher's door turns it back whatever made the draft (the daily
  draft, a designed draft, Post this, the phone), the daily draft and the designed drafts never pick a photo on a
  draft inside it, and Post this refuses one (`sample.used_lately`). The designed drafts draw the least recently
  used first on any surface and spread: one room and one event before any repeats, each leading with an event no
  post had inside `VARIETY_DAYS` while one is left, and a hero room the day's other designed drafts did not lead
  with. They never take an event from the daily post (the approved library holds 34 events, most with one to four
  photos; four posts a day under the daily post's hard 14-day event rule would leave mornings with nothing to post),
  so their event is kept apart (`designed_event`).
- **Why the photos repeated** (read from the code and the live database, 2026-10-15). The samples were the repeat:
  `design_samples.pick` took one photo per room and per event before the rotation, and the rarest rooms and events
  hold one or a few photos (of 1,871 approved candidates: the expo floor 1, backstage 2, after dark 13, on the floor
  15; 20 of 34 events have four photos or fewer), so the same few led every set; and the set was made again
  whenever the approved, sorted photos changed, 16 times in 21 hours as the sorter worked. Photo 11922 was in all
  16 sets, 890 in 12, 26780 in 11. Every set counted as a use (`photo_use` surfaces: post, site, sample), which sent
  those photos to the back for posts and the site but never kept them out of the next set. The site hero is never
  rotated, by design. The windows held for the daily draft (180 days on any draft) and at the door (180 days on
  anything that went out); Post this checked neither until the door, and `VARIETY_DAYS` covered only events and
  people. Of 1,913 approved photos 144 had passed Claude's final check, which the daily draft runs on the photos it
  picks; the age flag (removed by the ruling above) held 28 of them.
- **One Today page** (`dashboard/today.py`, `templates/today.html`): Needs you (every draft waiting, newest first,
  with its three choices and a reel playing inline with its sound; then quote requests, organizer notes and scout
  finds; then each alert with its fix), This week (what is set to go out, by day, as cards) and Went out (the last
  posts, each with its link on Instagram when Buffer gave one, and the 30-day numbers). The chips: Send a photo and
  All posts (`/history`: every post in plain words, the numbers by week). `/posts`, `/queue`, `/library?view=design`,
  the samples page and `/?show=` answer with a redirect. Music for reels and the library report moved to Photos,
  Music.
- **Plain words.** Queue is To approve; would publish is Practice run (posting is off); rejected is Skipped; dry run
  is practice run; the samples are Ideas where the word still shows. A big amber banner on every page while the
  publisher or the content lane is in practice run says posts are not going out and links to Settings, Agents.
- **Went out tells the truth, and the schedule is said.** Chris: "dashboard also says nothing has gone out yet and one
  did get posted within the last 24hrs. what is even the schedule for posting auto and why does this seem so messy?"
  Buffer sent queue post 2 at 15:30 UTC; the Mini never wrote it down. The publisher asked Buffer about every
  scheduled post every ten minutes, one due tomorrow as much as one due now (about 14 requests an hour), so the
  suite's own 24-hour Buffer ceiling (200 of 250) was reached by 12:34 UTC and every request after that was refused,
  the check of that post and the scheduling of the approved post 5 among them. Now a post is asked about from five
  minutes before its time (`publisher.due_at`); a network Buffer says went out is written down at once even when
  another network on the row cannot be read; and once an hour one request reads what Buffer says was sent on this
  company's channels (`publisher.reconcile_sent`): each of the suite's posts among them goes into `post_history`, a
  scheduled post whose every network went out is published with its ping, and the list is kept so Went out on
  Today also shows a post sent from Buffer itself. The daily numbers count every post the suite scheduled as ours.
  Today has How posting works, read from the code: the 8:00 draft for the next day, the designed drafts' hours,
  each network's times (`POST_TIMES` and what the learner moved), the design of each weekday (`content.DESIGNS`, the
  building day), what goes out next and the next draft. Pinned by `tests/test_went_out.py`, each seen to fail first.
- **Four tabs: Today, Photos, Bookings, Settings.** More became Settings: the system pages first (Agents, Errors,
  Keys, Buffer), then the pages that find work (Outreach, Scout, Search, Learner); `/more` opens it. Every alert,
  on the Errors page and in Needs you, is one card per kind with the button that fixes it where a fix exists (Sign
  in to Drive, add a key, link the channels, approve a failed post again, run an agent again; `dashboard/alerts.py`)
  and Dismiss. An alert about a network that is switched off (`POST_NETWORKS`) never shows. Every tap target is 44
  px or more.

## 2026-10-15: the dashboard away from home, never public without Access

Chris: "can i reach this dashboard without running tailscale when im out of town?" Asked, he chose a private web
address: a Cloudflare Tunnel from the Mini to `dash.eventcaliber.com`, Cloudflare Access in front (a one-time code
sent to chriskimages@gmail.com, only that email, a session of one week), the dashboard's own password behind it.
Free; nothing opened on the Mini's network; one setup run on the Mini (docs/SETUP.md, 9a).

- The rule: **never public without Access.** Every gate fails closed:
  - The tunnel starts only with its token, the address, the Access team, the application's AUD tag and the one
    email in place, and only when every path of the address answers Cloudflare's sign-in from outside, never the
    dashboard (`core/tunnel.py`, `core/access.py` `check_outside`). cloudflared is stopped the moment Cloudflare
    routes it to anything but `http://127.0.0.1:4610` (another port, another machine, another name), or when it
    has not said its routes within two minutes. Our tunnel reaches our dashboard and nothing else on the shared
    Mini.
  - The dashboard refuses whatever came through Cloudflare (its `Cf-Ray` or `Cf-Connecting-Ip` header, or the
    tunnel's address) without a valid Access token for his email: RS256, signed by the team's keys, for this
    application, from the team, unexpired. Missing settings or keys that cannot be read: refused, before any page,
    the login included (`core/access.py` `refusal`, the dashboard's middleware). The password is still asked
    behind it; the session cookie is Secure over https.
  - `scripts/install-daemons.sh` installs the service (`launchd/com.chriskennedyimages.conventionsocial.tunnel`)
    only when `ccs tunnel check` passes, and otherwise removes our own. No other cloudflared service and no
    Tailscale setting is touched; the Tailscale address keeps working as it is.
- The token lives in `.env` (or the Keychain) only: never in the repo, a file under /Library, a command line or
  on screen. cloudflared reads it from its environment.
- The links move to the new address only once the tunnel runs (`ccs tunnel status --use`, from go-live). Behind
  Access only a browser gets in, so Approve on a ping opens the approve page (one more tap) and the ping carries no
  picture: the ntfy app's own request would meet Cloudflare's sign-in, and its Approve would look done when nothing
  was. Letting the ping's token paths bypass Access would make them public on the token alone: not done unless he
  says so. Chris, 2026-10-15: "Keep the extra tap", and the address `dash.eventcaliber.com`.
- Chris: "does this have a place for the sample posts reels that get created". Every page and file the dashboard
  serves goes through the tunnel, the design samples and their reels included (a reel plays with its sound and seeks
  with byte ranges). Every answer through Cloudflare says `Cache-Control: private, no-store`: Cloudflare keeps .jpg
  and .mp4 for two hours unless told otherwise, and his photos never stay in its cache. Cloudflare's free plan takes
  uploads up to 100 MB (a photo from the phone) and its terms may limit a free site that serves a lot of video.

Pinned by `tests/test_tunnel.py`.

## 2026-10-15: one change at a time, shown first, and one voice

Chris, the same day, as the number of sessions grew:

- "show me all examples always for approval": every visible change, small
  fixes included, reaches him as a rendered before and after; nothing merges
  without his OK on it.
- "no, you coordinate, i mistakenly thought i was in this session so message
  the agent": one coordinating session talks to him; the others report to it.
- "you can merge if you ask me so merge": on his yes, Claude merges, pinned to
  the tested commit.
- "Let's slow down on merges and let things catch up if they're still things
  working?": one change at a time on the Mini, each deployed and checked live
  before the next. That afternoon six or seven sessions ran full test suites
  at once on the Mini; the updater's 30-minute test run timed out on every
  update from 14:52 to 21:52, and a test that read the Mini's own
  `wrangler.live.jsonc` stopped `scripts/go-live.sh` (both fixed the same
  night: the updater gives the suite an hour; tests never see that file).
- "Put that in law": `CLAUDE.md`, "How changes reach the Mini".

## 2026-10-16: the logos roll like the ticker, on the black, no tiles

Chris, on the strip live: "The white background on the logos are intense!
Could it be a scroller too without the white background?" Asked how, he
chose "Their own colors, no tiles" and "Same speed as the ticker".

- The strip is the ticker's own band (`.ticker.logos`, `site/clients.py`
  `clients_body`): the same fade over the gutter at both ends, the same start
  on the text column, the same keyframes, the run doubled for the loop and the
  copy silent to readers. Its speed is the ticker's: `site.js` sets its
  duration to the ticker's scaled by the two runs' widths. It holds under the
  pointer and under a finger, stands still for visitors who ask for reduced
  motion, and never scrolls the page sideways. The logos load at once (a lazy
  copy would arrive late as it rolls in).
- Each logo sits on the site's black as itself, at one optical height. Ink
  that does not read there gets a light version (`site/clients.py`
  `relight`): black and grey become the site's light; a dark colour (a navy, a
  dark green) keeps its hue, lifted to 4.5 to 1; a brand colour (chroma 0.15
  or more: the Nationals red, the AHA red, APTA's magenta, the ACU's stripes)
  stays as it is. It is decided area by area: dark ink sitting on the black is
  relit, dark ink inside the logo's own light ink (C.A.S.E.'s letters on its
  tree) keeps its colour. A logo drawn on a white box (the AP's) loses the box.
  offer.json records per logo whether it was relit (`relit`, measured by the
  code, pinned against it): nine of the twelve; the Washington Nationals, the
  American Heart Association and CPAC read on the black as they are.
- Pinned by `tests/test_client_logos.py`.

## 2026-10-16: one photo, one post; the door says where the photo is

Chris: "Why why why is it giving me this error when nothing was posted with this image!? Very frustrating because it's
a good reel." Read from the live database: the 8:00 daily draft (post 7, the reel) picked its photos at 12:00 UTC and
spent seven minutes checking and rendering; the designed draft started at 12:02, picked the same photo 894 (both draw
the least used first) and saved post 6, the spotlight, at 12:03; the daily draft saved post 7 at 12:07 with 894 and
47350 in it. Each picker left out every photo in an open post; the other's picks did not exist yet. When he approved
the reel, the publisher's door turned it back with "Photo 894 already went out as post #6", though post 6 was only
scheduled. He pulled post 6 back himself to post the reel.

- **One draft picked at a time.** The roads that pick from the library hold one lock from the pick to the save
  (`content.DRAFTING`): the daily draft and Post this wait for it (up to 15 minutes), a designed draft that finds it
  held waits for the next hour.
- **The save refuses a taken photo.** Saving a draft looks again, inside one write transaction, for each of its photos
  on another post inside the repeat window (open, scheduled or sent; a skipped one is not), and refuses the draft when
  one is there (`content.PhotosTaken`). The daily draft says so and its window tries the day again; a designed draft
  waits for the next hour; Post this says why on the press.
- **The door tells the truth.** "Photo 894 already went out as post #6 on Thu Oct 15" only when post 6 went out;
  otherwise "Photo 894 is already in post #6, set to go out Sun Oct 18 at 10:00 am. Pull post #6 back to use it here,
  or Skip this one.", with the post that holds the photo linked on the draft and on Today (`publisher.held_words`,
  `rule_report.held_by`). A new approve clears it; the door says it again if the photo is still held.
- Pinned by `tests/test_today.py` (`OnePhotoOnePost`), each seen failing first.

## Standing rules from the brief

- CPAC, the ACU and their affiliates are never contacted, by code
  (2026-10-13, above).

- Nothing publishes without Chris's Approve on the dashboard, until he says
  otherwise. He said so once: a photo he sends from the share sheet is
  approved by the act of sending (2026-10-15, Post to Event Caliber). Every
  agent that sends or publishes starts in dry run (`core/settings.py`).
- Nothing in Drive is ever modified, moved, renamed or deleted
  (`drive/`, pinned by `tests/test_drive_readonly.py`).
- No photo is eligible until Chris clears its folder or the photo itself.
  A do-not-use list is honoured everywhere. (Until 2026-10-15 this also said
  "Never post anyone who may be a minor"; see "no age gate" above.)
- Never claim to be a convention's official photographer or any affiliation
  unless Chris confirms it for that event (`ai/copy_rules.py`, rule
  `affiliation`).
- Captions and copy: plain, short sentences, no dashes, never promise what
  the system does not do today.
- The dashboard is never public without Cloudflare Access in front: no
  Access, no page (2026-10-15, above).

## 2026-10-23: different photos every draft; CPAC and the ACU welcome; clean code

Chris: "I seem to always get the same style and pic in my drafts." Measured: the second photo of every
designed draft came from one folder (CPAC Texas 2022, "All Final edited High-Res images": 5081, 5087,
5088, 5089, 5090, 5093, 5094). Today's daily reel took four consecutive frames of one folder ("Texas
Sunday missing Panel"). The cause: among photos used alike and rated alike, the rotation fell back to
file order, so one big folder's next frame always won. The daily post also spread its photos by room
but not by event.

- Least used first, still. Then the caller's quality order. Only photos equal on both are put in a
  chance order (library/report.rotate).
- In a post: a new event first, then a new shoot (Drive folder) of an event already in, and a shoot
  repeated only when nothing else is left (designed.spread). The daily post uses the same rule
  (content.order_pool).
- Chris: "You can use more than one from CPAC or ACU. They were an enormous client for 10yrs and we
  worked through the year on this one conference." No cap on CPAC or ACU photos. Two CPAC shoots may
  share a post; variety comes from the shoots, not from leaving the client out.
- Chris: "I want this code very clean! Workarounds just leave breadcrumbs for a mess up in the future."
  Causes are fixed, not patched. Code nothing uses is deleted in the same change.

## 2026-10-23: the five 3D reels, in rotation

Chris: "There should be 5 different style reels (all very different)"; "add all the new reels approved and
created to the rotation"; the reels are 3D, cinematic, the photos exact, no light over a photo, never a ring
drawn around one, a photo never pushes forward. After a day of samples (reels3d/, Remotion + three.js), the
five styles: wall, loop, ring, gallery, orbit.

- A reel is one of the five at random, never the same style twice in a row (content.reel_style).
- The post's photos are the reel's photos: Loop's visited cards, Wall's lifting heroes, Ring's lead cards,
  Gallery's prints, Orbit's cards. Around them, where a style has a wall or a grid, approved photos from the
  library's local copies, one per room per shoot (reels3d.fillers): varied, never the post's own.
- The rooms reel (PIL, 2026-10-11) is out of the rotation; the Design page's sample still shows it.
- The cover is a frame of the reel, per style (reels3d.COVER_S); the publisher sends that offset to Buffer.
- Rendering needs Node on the Mini (reels3d/node_modules): the updater installs the packages and Remotion's
  browser when reels3d/ changes or they are missing. No Node, no reel: the draft falls back to a carousel of the
  same photos and says why, as before.
- Loop, after six rounds on 2026-10-23: "Fuck it, it's fine." It stays as it is.

## 2026-10-23: mostly reels, and a reel's ping says so

Chris: "Are the reels back? All I get are stills and we built the reels part which was my favorite part, but you
somehow managed to bury them". Asked how often, he chose **"Mostly reels"**. Asked whether a reel's ping should say
so and open straight to it playing, he said **yes**.

- The daily 8:00 post is a reel every event day with a music track. The week's still designs (spotlight, poster,
  scan, cascade, select) are for the days without music. A building day stays one photo, and a day with too few
  photos falls back as before.
- Two of every three designed drafts are reels, while there is music. The third is the still design used least
  lately, so the stills still take turns.
- A reel's ping title starts with "Reel:". Tapping it opens the draft with the reel already playing. It plays
  silent, because phones only allow sound after a tap, so one more tap turns the sound on.
- Why it was buried: only Saturday was a reel day; designed drafts rotated through all nine designs (1 reel in 9);
  the lane paused while 3 drafts waited (Oct 18 to 22); and the ping showed only the reel's cover still.
- Known limit: there is one reel style (rooms), so the reels will look alike until a second style is made.

## 2026-10-24: after the audit; what the founder delegated

Chris, on the audit's "needs your decision" list: "you do it all please. you're more careful." Settled, each
reversible on the Keys page or in this file:

- **A photo never pushes forward is Loop's rule.** It was given twice while Loop was being made ("the photos
  should not punch out"). Wall lifts its hero toward the camera, Ring brings its hero forward, Orbit's front card
  grows, Gallery dollies in; Chris watched each of those as a finished video and kept them. The rule stands for
  Loop and for any new style unless he says otherwise for that style.
- **One designed draft a day** (DESIGNED_PER_DAY=1, from 3) while Instagram has one slot a day. Seven posts were
  scheduled a day apart through 31 October because every approved post adds a day; two drafts a day (the daily
  post and one designed) is what one slot can carry. A second daily slot (POST_TIMES) is Chris's call, not made.
- The two corrupt token sidecars from 11 October (world-readable, a refresh token inside) are deleted; sidecars
  are to be written 0600 from now on.
- The outreach lane stays as Chris switched it (live since 11 October): it sends only rows he approved
  (agents/outreach.send_approved), and nothing has been sent.
- Loop stays as it is (23 October: "Fuck it, it's fine"); the art director is to be told its glass loop is the
  design, not a defect (its own session).

## 2026-10-25: the Anthropic credit, the cap, Claude sorting; Atlas and the other fleet untouched

Chris's Max 20x plan pays $200 of API credit a month into his Console organization ("Chris's Individual Org",
linked 14 October; next credit 17 November; unused credit expires; when it is gone Anthropic stops every call
and bills no card). This suite's key is in that organization: the Console showed $7.69 of credit used since
the link and the suite alone had spent $7.16–$8.58 in those days. Checked before deciding ("I want to check
where that $200 sits and what Anthropic says about it"), then "Go ahead with it":

- **The cap is $150, counted from the 17th** (AI_MONTHLY_CAP_USD=150, AI_CAP_RESETS_ON=17), so the cap and the
  credit count the same days and two cycles cannot stack inside one credit. $50 of credit and the $32.36
  purchased balance stay as headroom for anything else in the organization.
- **Photo sorting goes to Claude** (CLASSIFY_BACKEND=claude, CLASSIFY_MODEL=claude-opus-5, CLASSIFY_PER_RUN=100):
  Ollama graded 7,102 of 8,578 undecided photos a 4, so "best first" ranked nothing. About a cent a photo,
  ~1,300 a day; the unsorted event and architecture photos are done in about eight days.
- **Atlas is not Anthropic.** "Atlas" is the Atlas Cloud video API (Seedance) in Chris's other fleet (its own repo
  and .env on the Mini), capped at $16 a week in its own atlas_budget.py and its own ledger; nothing in this suite
  can reach it, and nothing in that fleet was changed, as he asked.
- The photo-review work (shoots first, then Claude grades the pool, then a faster per-photo tab) is its own
  session, started when Chris is at the Mac: "We can wait until on the Mac for that specifically."


- Loop stayed as it was that afternoon (23 October: "Fuck it, it's fine") until the evening's rework, next
  entry; the art director is to be told its glass loop is the design, not a defect (its own session).

## 2026-10-24: the Loop reel, in Chris's words (approved; reels3d/src/Loop.tsx)

"If you get this right this time, please save that prompt." Saved here and in memory; Loop is not changed
again without his word.

- **The loop:** one loupe of liquid glass, one size, that travels one smooth curve for the whole reel: in from
  beyond the first photo, across each of the reel's four photos side to side, on to the next, out beyond the
  last. It never stops, never changes. "The loop move fluidly." Later that night: "the loop itself is moving too
  fast. It's supposed to crawl and creep"; "it should slow on full bleed"; "ONLY TOUCH THE LOOP NOTHING ELSE FROM
  THE LAST APPROVED ONE." So it reaches and leaves each photo on the frames of a steady pace (the grid's rests,
  slides and enlarging are untouched) and in between creeps, slowest while the photo fills it, quicker over its
  edges, the speed changing smoothly. Approved 2026-10-25 ("Yes, it's right"). Inside it only the photo under it,
  magnified mildly; "when you put your eye to a loop there are no reflections inside of the loop itself, just on
  the edges to show the liquid glass effect and magnification." "The whole point is the loop! If I didn't use a
  loop I would only then bring the photo closer. The LOOP magnifies, not the photo being lifted closer."
- **The grid:** "There is no camera." Level rows of cards, each its own shape, tight dark gaps; a 3:2 card is two
  thirds of the width ("the grid is too small" at less). "The background moves in 2d with the loop crawling over
  the photos grid." While the loop crosses a card the grid rests and "the whole grid enlarges to make the photo
  bigger when the loop has crawled to that image" (a little, x1.2), the rest of the grid dark; "the loop doesn't
  shrink but the grid should" as the loop leaves, and it slides level to the next card. "The photo should never
  lift from the background." "The loop and photo itself don't transition to anything else other than what they
  are." "We pick the images the loop is going to on the grid and they are the reel's images": "do 4 images and go
  slower on the reel." A fifth or sixth photo fills the grid.
- **Never again:** the photo lifting or pushing toward the viewer; a zoom that reads as the photo coming closer;
  a thick drop-like lens ("like a raindrop magnified"); a flat disc over faces; reflections inside the lens; the
  grid shrinking at the close ("the ending goes back to the photo push"); a mix of effects ("that's a mix of
  everything we created"); anything drawn around a photo; light over a photo.


## 2026-10-24: the quote form behind Turnstile

Open since the 16 October audit ("Quote form spam, Turnstile: open; your site key"). Chris, on the day's fixes: "you do
it all please, you're more careful".

- The Cloudflare Turnstile widget "eventcaliber.com quote form" (managed, eventcaliber.com and www) is on the form,
  right above Send, shown only when Cloudflare wants the visitor to tick a box; most visitors never see it. Send waits
  for the token when it has to and says so; a browser that cannot load the check is told to email instead.
- The Worker confirms every request's token with Cloudflare and refuses without one, with a token Cloudflare does not
  confirm, one solved on another site or for another action, or when Cloudflare does not answer. Without its secret key
  the form is closed and says so, with the email: never open to bots.
- The site key is in the code (public); the secret key is a Worker secret only, staged with `wrangler versions secret
  put` so it goes live with the next deploy and never reaches `.env` or the repo.
