"use strict";

(function () {
  const $ = (id) => document.getElementById(id);
  const ROW_HEIGHT = 22;
  const RULER_HEIGHT = 38;
  const WAVE_HEIGHT = 94;
  const MARKER_HEIGHT = 22;
  const MAX_XML_BYTES = 50 * 1024 * 1024;
  const MAX_AUDIO_BYTES = 200 * 1024 * 1024;
  const MAX_XML_ELEMENTS = 100000;
  const MAX_JSON_BYTES = 5 * 1024 * 1024;
  const MAX_CANVAS_PIXELS = 36000000;
  const MAX_XML_DEPTH = 256;

  const state = {
    sequence: null,
    audioFile: null,
    audioBuffer: null,
    waveformPeaks: null,
    audioUrl: null,
    analysis: null,
    vocals: null,
    lyrics: null,
    syncCheck: null,
    rows: [],
    lanes: [],
    pxPerSecond: 22,
    collapsedGroups: new Set(),
    collapsedProps: new Set(),
    selectedEffect: null,
    // Editing: selection is a list of {channel, effect}; effects are replaced, never
    // changed in place, so undo can restore a channel's earlier effect list.
    selection: [],
    undo: [],
    redo: [],
    dirty: false,
    baselineEffects: new Map(),
    editRevision: 0,
    exportPending: false,
    exportRequestId: 0,
    drag: null,
    clipboard: null,
    cursorCs: 0,
    reviewSelection: null,
    reviewDrag: null,
    reviewDirty: false,
    reviewBaseline: null,
    animationFrame: 0,
    audioRequestId: 0,
    audioDecodePending: false,
    analysisRequestId: 0,
    sequenceRequestId: 0,
    vocalRequestId: 0,
    lyricRequestId: 0
  };

  // Sync check tolerances, in seconds.
  const SYNC_ON_TIME = 0.04;
  const SYNC_NEAR_MISS = 0.15;
  // A "big lighting change" is at least this many channels starting together.
  const SYNC_CLUSTER = 4;

  const audio = $("audioPlayer");
  const canvasViewport = $("canvasViewport");
  const labelsViewport = $("labelsViewport");
  const playhead = $("playhead");

  function setBanner(message, kind) {
    const banner = $("analysisBanner");
    $("analysisMessage").textContent = message;
    banner.className = "analysis-banner" + (kind ? " " + kind : "");
    if (kind === "error" && typeof remember === "function") remember("showed: " + message);
  }

  const ENGINE_GONE = "The program's engine is not answering. Close LOR Sequencer and open it " +
    "again; your files are not affected.";

  // Plain words for why a file or step failed, to follow "... could not be opened: ".
  function problemText(error) {
    if (!error) return "an unknown problem.";
    if (error.name === "SyntaxError") {
      return "it is not in the expected format. It may be damaged, or a different kind of file.";
    }
    if (error.name === "NotReadableError" || error.name === "NotFoundError") {
      return "the file could not be read. It may have been moved, or be open in another program.";
    }
    if (error.name === "EncodingError") {
      return "the audio could not be decoded. Try an MP3 or WAV copy of the song.";
    }
    const text = String(error.message || error).trim();
    return text ? text.replace(/([^.!?])$/, "$1.") : "an unknown problem.";
  }

  // Every request to the local engine goes through here: a stopped engine, a refusal
  // and an unreadable answer each get a message that says what to do.
  async function callEngine(path, body, type) {
    let response;
    try {
      response = await fetch(path, { method: "POST", headers: { "Content-Type": type }, body });
    } catch {
      throw new Error(ENGINE_GONE);
    }
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      const error = new Error(payload && payload.error ? payload.error
        : "The program could not do that step (code " + response.status + "). Try again.");
      error.status = response.status;
      error.reference = payload && payload.reference;
      throw error;
    }
    if (payload === null) throw new Error("The program sent back an answer it could not read. Try again.");
    return payload;
  }

  function formatTime(seconds) {
    const total = Math.max(0, Math.floor(seconds));
    return Math.floor(total / 60) + ":" + String(total % 60).padStart(2, "0");
  }

  function formatCentiseconds(value) {
    const cs = Math.max(0, Math.floor(value));
    return formatTime(cs / 100) + "." + String(cs % 100).padStart(2, "0");
  }

  function parseXmlDocument(text) {
    if (text.length > MAX_XML_BYTES) throw new Error("Sequence exceeds the 50 MiB input limit.");
    if (/<!DOCTYPE|<!ENTITY/i.test(text)) throw new Error("DOCTYPE and entity declarations are not accepted.");
    const doc = new DOMParser().parseFromString(text, "application/xml");
    if (doc.querySelector("parsererror")) throw new Error("The selected file is not well-formed XML.");
    const root = doc.documentElement;
    if (!root || root.localName !== "sequence") throw new Error("Expected a native S6 sequence root element.");
    if (root.getAttribute("saveFileVersion") !== "15") {
      throw new Error("Only reviewed S6 LOREDIT saveFileVersion 15 files are supported.");
    }
    let count = 0;
    const stack = [{ node: root, depth: 1 }];
    while (stack.length) {
      const item = stack.pop();
      count += 1;
      if (count > MAX_XML_ELEMENTS) throw new Error("Sequence exceeds the 100,000-element safety limit.");
      if (item.depth > MAX_XML_DEPTH) throw new Error("Sequence exceeds the 256-level XML nesting limit.");
      for (const child of item.node.children) stack.push({ node: child, depth: item.depth + 1 });
    }
    return doc;
  }

  function parseSequence(doc, filename) {
    const root = doc.documentElement;
    const durationCs = Number(root.getAttribute("totalCentiseconds"));
    if (!Number.isSafeInteger(durationCs) || durationCs <= 0 || durationCs > 2160000) {
      throw new Error("Sequence duration is missing or outside the supported range.");
    }
    const propsRoot = root.querySelector(":scope > SequenceProps");
    if (!propsRoot) throw new Error("Sequence is missing its native SequenceProps section.");
    const props = [];
    let effectCount = 0;
    const effectTypes = {};
    for (const propNode of propsRoot.children) {
      if (propNode.localName !== "SeqProp") continue;
      const prop = {
        id: propNode.getAttribute("id") || "",
        name: propNode.getAttribute("name") || "(unnamed prop)",
        channels: []
      };
      for (const channelNode of propNode.children) {
        if (channelNode.localName !== "channel") continue;
        const channel = {
          row: channelNode.getAttribute("row") || "0",
          col: channelNode.getAttribute("col") || "0",
          color: channelNode.getAttribute("color") || "0",
          effects: [],
          node: channelNode,
          edited: false
        };
        for (const effectNode of channelNode.children) {
          if (effectNode.localName !== "effect") continue;
          const start = Number(effectNode.getAttribute("startCentisecond"));
          const end = Number(effectNode.getAttribute("endCentisecond"));
          if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) ||
              start < 0 || end <= start || end > durationCs + 100) {
            throw new Error("Invalid effect timing found in prop " + prop.name + ".");
          }
          const attributes = {};
          for (const attr of effectNode.attributes) attributes[attr.name] = attr.value;
          const type = attributes.settings || "UNKNOWN";
          effectTypes[type] = (effectTypes[type] || 0) + 1;
          channel.effects.push({ start, end, type, attributes });
          effectCount += 1;
        }
        prop.channels.push(channel);
      }
      props.push(prop);
    }
    if (!props.length) throw new Error("Sequence contains no SeqProp tracks.");

    const groups = [];
    const membership = new Map();
    const preview = root.querySelector(":scope > PreviewClass");
    if (preview) {
      for (const groupNode of preview.children) {
        if (groupNode.localName !== "PropGroup") continue;
        const group = {
          id: groupNode.getAttribute("id") || "group-" + groups.length,
          name: groupNode.getAttribute("Name") || "(unnamed group)",
          arrangement: groupNode.getAttribute("Arrangement") || "unspecified",
          memberIds: []
        };
        for (const member of groupNode.children) {
          if (member.localName !== "member") continue;
          const id = member.getAttribute("id");
          if (id) {
            group.memberIds.push(id);
            if (!membership.has(id)) membership.set(id, group.id);
          }
        }
        groups.push(group);
      }
    }

    const timingGrids = [];
    const gridsRoot = root.querySelector(":scope > TimingGrids");
    if (gridsRoot) {
      for (const gridNode of gridsRoot.children) {
        const name = gridNode.getAttribute("name") || gridNode.localName;
        if (gridNode.localName === "TimingGridFree") {
          const marks = [];
          for (const mark of gridNode.children) {
            if (mark.localName !== "timing") continue;
            const cs = Number(mark.getAttribute("centisecond"));
            if (Number.isSafeInteger(cs) && cs >= 0 && cs <= durationCs) marks.push(cs);
          }
          timingGrids.push({ name, kind: "free", marks });
        } else if (gridNode.localName === "TimingGridFixed") {
          timingGrids.push({
            name,
            kind: "fixed",
            spacing: Number(gridNode.getAttribute("spacing")) || 0,
            marks: []
          });
        }
      }
    }

    const audioName = root.getAttribute("musicFilename") || "";
    return {
      doc,
      yard: parseYard(doc),
      filename,
      name: root.getAttribute("musicTitle") || root.getAttribute("name") || filename,
      artist: root.getAttribute("musicArtist") || "",
      audioName,
      durationCs,
      durationSeconds: durationCs / 100,
      props,
      groups,
      membership,
      timingGrids,
      effectCount,
      effectTypes,
      channelCount: props.reduce((sum, prop) => sum + prop.channels.length, 0)
    };
  }

  function buildRows() {
    if (!state.sequence) return [];
    const sequence = state.sequence;
    const propsByGroup = new Map();
    const groupIds = new Set(sequence.groups.map((group) => group.id));
    for (const group of sequence.groups) propsByGroup.set(group.id, []);
    const ungrouped = [];
    for (const prop of sequence.props) {
      const groupId = sequence.membership.get(prop.id);
      if (groupId && groupIds.has(groupId)) {
        propsByGroup.get(groupId).push(prop);
      } else if (groupIds.has(prop.id)) {
        // S6 can include a channel-less SeqProp whose ID is the PropGroup ID.
        // The group header already represents that placeholder; don't create a
        // duplicate empty prop row under "Ungrouped props".
        if (prop.channels.length) propsByGroup.get(prop.id).push(prop);
      } else {
        ungrouped.push(prop);
      }
    }
    const rows = [];
    function appendProp(prop) {
      rows.push({ kind: "prop", prop });
      if (!state.collapsedProps.has(prop.id)) {
        prop.channels.forEach((channel, index) => rows.push({
          kind: "channel", prop, channel, channelIndex: index
        }));
      }
    }
    for (const group of sequence.groups) {
      const members = propsByGroup.get(group.id) || [];
      if (!members.length) continue;
      rows.push({ kind: "group", group, count: members.length });
      if (!state.collapsedGroups.has(group.id)) members.forEach(appendProp);
    }
    if (ungrouped.length) {
      const id = "__ungrouped__";
      rows.push({ kind: "group", group: { id, name: "Ungrouped props" }, count: ungrouped.length });
      if (!state.collapsedGroups.has(id)) ungrouped.forEach(appendProp);
    }
    state.rows = rows;
    return rows;
  }

  function timingGridMarks(grid) {
    if (grid.kind === "fixed" && grid.spacing > 0 && state.sequence) {
      const count = Math.min(50000,
        Math.floor(state.sequence.durationCs / grid.spacing) + 1);
      return Array.from({ length: count }, (_, index) => index * grid.spacing);
    }
    return grid.marks;
  }

  function sortedTimes(events) {
    return events.map((event) => Number(event.time))
      .filter((value) => Number.isFinite(value)).sort((a, b) => a - b);
  }

  function nearest(sorted, value) {
    let low = 0;
    let high = sorted.length - 1;
    while (low < high) {
      const middle = (low + high) >> 1;
      if (sorted[middle] < value) low = middle + 1;
      else high = middle;
    }
    let best = Infinity;
    for (const index of [low - 1, low]) {
      if (index >= 0 && index < sorted.length) {
        best = Math.min(best, Math.abs(sorted[index] - value));
      }
    }
    return best;
  }

  // Strong musical moments (bar starts, crash candidates, the loudest tenth of the
  // transients) checked against big lighting changes (several channels starting
  // together). A moment whose nearest big change is 40-150 ms away is a possible
  // out-of-sync hit; farther away it simply has no lighting response, which may be
  // intended. This reports evidence and the tolerance; it does not judge intent.
  function syncCheck() {
    const analysis = state.analysis && state.analysis.analysis;
    if (!analysis || !state.sequence) return null;
    if (state.syncCheck && state.syncCheck.analysis === analysis &&
        state.syncCheck.sequence === state.sequence) return state.syncCheck;
    const counts = new Map();
    for (const prop of state.sequence.props) {
      for (const channel of prop.channels) {
        for (const effect of channel.effects) {
          counts.set(effect.start, (counts.get(effect.start) || 0) + 1);
        }
      }
    }
    const changes = Array.from(counts.entries())
      .filter(([, count]) => count >= SYNC_CLUSTER).map(([cs]) => cs / 100)
      .sort((x, y) => x - y);
    const onsets = (analysis.onsets || []).slice()
      .sort((x, y) => (Number(y.strength) || 0) - (Number(x.strength) || 0));
    const strongest = onsets.slice(0, Math.max(1, Math.floor(onsets.length / 10)));
    const moments = sortedTimes([].concat(analysis.downbeats || [], analysis.crashes || [],
      strongest)).filter((time, index, all) => index === 0 || time - all[index - 1] > 0.03);
    const flagged = [];
    let onTime = 0;
    for (const time of moments) {
      let best = null;
      let bestChange = null;
      let low = 0;
      let high = changes.length - 1;
      while (low < high) {
        const middle = (low + high) >> 1;
        if (changes[middle] < time) low = middle + 1;
        else high = middle;
      }
      for (const index of [low - 1, low]) {
        if (index >= 0 && index < changes.length) {
          const offset = changes[index] - time;
          if (best == null || Math.abs(offset) < Math.abs(best)) {
            best = offset;
            bestChange = changes[index];
          }
        }
      }
      if (best == null) continue;
      const distance = Math.abs(best);
      if (distance <= SYNC_ON_TIME) onTime += 1;
      else if (distance <= SYNC_NEAR_MISS) {
        const ms = Math.round(distance * 1000);
        flagged.push({ time, offset_ms: Math.round(best * 1000),
          change_cs: Math.round(bestChange * 100),
          method: "nearest big lighting change is " + ms + " ms " + (best < 0 ? "early" : "late") });
      }
    }
    state.syncCheck = { analysis, sequence: state.sequence, moments: moments.length, onTime,
      flagged };
    return state.syncCheck;
  }

  function effectsAt(seconds, toleranceCs) {
    const cs = seconds * 100;
    const found = [];
    for (const prop of state.sequence.props) {
      prop.channels.forEach((channel, index) => {
        for (const effect of channel.effects) {
          if (effect.start - toleranceCs <= cs && cs < effect.end + toleranceCs) {
            found.push({ prop, channelIndex: index, effect });
          }
        }
      });
    }
    return found;
  }

  function inspectMoment(seconds, lane) {
    const inspector = $("inspectorContent");
    inspector.replaceChildren();
    const add = (text, primary) => {
      const item = document.createElement("div");
      if (primary) item.className = "inspector-primary";
      item.textContent = text;
      inspector.appendChild(item);
    };
    add(formatCentiseconds(seconds * 100) + (lane ? " · " + lane.label : ""), true);
    if (lane && lane.kind === "lyrics") {
      const line = lane.events.find((item) => item.start <= seconds && seconds < item.end);
      if (line) {
        add("\u201c" + line.text + "\u201d", true);
        add(line.verified ? "Lyric text from an imported file" :
          "Transcribed automatically: unverified until reviewed");
        if (line.words && line.words.length) {
          add("Words: " + line.words.map((word) => word.text + " " +
            formatCentiseconds(word.start * 100)).join(" · "));
        }
      }
    }
    if (lane && lane.kind === "offbeat") {
      const hit = lane.events.find((item) => Math.abs(item.time - seconds) < 0.02);
      if (hit) {
        add("Strong musical moment; " + hit.method + " (on time is within " +
          Math.round(SYNC_ON_TIME * 1000) + " ms).", true);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "tool-button inspector-action";
        button.id = "retimeButton";
        button.textContent = "Retime the lighting change to this moment";
        button.addEventListener("click", () => retimeToMoment(hit));
        inspector.appendChild(button);
      }
    }
    const found = effectsAt(seconds, 10);
    const starting = found.filter((item) => Math.abs(item.effect.start - seconds * 100) <= 10);
    const names = Array.from(new Set(found.map((item) => item.prop.name)));
    add(starting.length + " effect(s) start within 0.1 s; " + names.length +
      " prop(s) lit: " + names.slice(0, 14).join(", ") + (names.length > 14 ? ", …" : ""));
  }

  function handleMarkerClick(event) {
    if (!state.sequence) return;
    const canvas = $("markersCanvas");
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const lane = state.lanes[Math.floor((event.clientY - rect.top) / MARKER_HEIGHT)];
    let seconds = clampReviewSeconds(Math.max(0, x / state.pxPerSecond));
    if (lane && lane.kind !== "lyrics" && lane.kind !== "energy" && lane.kind !== "tempo") {
      // Snap to the nearest marker within 6 pixels, so a click lands on the event.
      const times = sortedTimes(lane.events.map((item) =>
        ({ time: item.time != null ? item.time : item.start })));
      let best = null;
      for (const time of times) {
        if (Math.abs(time - seconds) * state.pxPerSecond <= 6 &&
            (best == null || Math.abs(time - seconds) < Math.abs(best - seconds))) best = time;
      }
      if (best != null) seconds = best;
    }
    seconds = clampReviewSeconds(seconds);
    seekAudio(seconds);
    inspectMoment(seconds, lane);
  }

  function buildLanes() {
    const lanes = [];
    for (const grid of state.sequence ? state.sequence.timingGrids : []) {
      const marks = timingGridMarks(grid);
      if (marks.length) lanes.push({
        label: grid.name,
        source: "LOREDIT",
        kind: "native",
        events: marks.map((cs) => ({ time: cs / 100 }))
      });
    }
    const analysis = state.analysis && state.analysis.analysis;
    if (analysis) {
      if (analysis.beats && analysis.beats.length) lanes.push({
        label: "Beat candidates", source: "librosa", kind: "beats", events: analysis.beats
      });
      if (analysis.downbeats && analysis.downbeats.length) lanes.push({
        label: "Downbeat candidates", source: "librosa", kind: "downbeats", events: analysis.downbeats
      });
      if (analysis.onsets && analysis.onsets.length) lanes.push({
        label: "Audio transients", source: "librosa", kind: "onsets", events: analysis.onsets
      });
      if (analysis.energy && analysis.energy.length) lanes.push({
        label: "RMS energy envelope", source: "librosa", kind: "energy", events: analysis.energy
      });
      if (analysis.phrase_boundaries && analysis.phrase_boundaries.length) lanes.push({
        label: "Estimated 4-bar phrases", source: "heuristic", kind: "phrases", events: analysis.phrase_boundaries
      });
      if (analysis.section_candidates && analysis.section_candidates.length) lanes.push({
        label: "Section candidates", source: "estimated", kind: "sections", events: analysis.section_candidates
      });
      if (analysis.hard_stops && analysis.hard_stops.length) lanes.push({
        label: "Near-silence candidates", source: "estimated", kind: "stops", events: analysis.hard_stops
      });
      if (Array.isArray(analysis.tempo_curve) && analysis.tempo_curve.length) lanes.push({
        label: "Tempo (local BPM)", source: "librosa", kind: "tempo", events: analysis.tempo_curve
      });
      if (Array.isArray(analysis.high_hits) && analysis.high_hits.length) lanes.push({
        label: "High-pitched hits", source: "librosa", kind: "hits", events: analysis.high_hits
      });
      if (Array.isArray(analysis.crashes) && analysis.crashes.length) lanes.push({
        label: "Cymbal crash candidates", source: "heuristic", kind: "crashes", events: analysis.crashes
      });
    }
    if (state.lyrics && state.lyrics.lines.length) lanes.push({
      label: state.lyrics.source === "transcribed" ? "Lyrics (unverified)" : "Lyrics",
      source: state.lyrics.source, kind: "lyrics", events: state.lyrics.lines
    });
    const sync = syncCheck();
    if (sync) lanes.push({
      label: "Possible out-of-sync hits", source: "check · " + sync.flagged.length +
        " of " + sync.moments, kind: "offbeat", events: sync.flagged
    });
    if (state.vocals) {
      if (state.vocals.regions && state.vocals.regions.length) lanes.push({
        label: "Vocal regions", source: "heuristic", kind: "vocal-regions", events: state.vocals.regions
      });
      if (state.vocals.syllables && state.vocals.syllables.length) lanes.push({
        label: "Vocal syllables / holds", source: "heuristic", kind: "syllables", events: state.vocals.syllables
      });
    }
    // Arranged like a DAW reference area: what is sung first, right under the
    // waveform, then song structure, then rhythm, then the sequence's own grids.
    const order = ["lyrics", "vocal-regions", "syllables", "sections", "stops", "phrases",
      "downbeats", "beats", "tempo", "crashes", "hits", "onsets", "energy", "native", "offbeat"];
    lanes.sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind));
    state.lanes = lanes;
    const chosen = state.reviewSelection;
    if (chosen) {
      const target = reviewLane(laneByKind(chosen.kind));
      if (!target || !target.owner[target.key].includes(chosen.event)) state.reviewSelection = null;
    }
    return lanes;
  }

  function makeLabel(text, className, source, events) {
    const div = document.createElement("div");
    div.className = className;
    const span = document.createElement("span");
    span.textContent = text;
    div.appendChild(span);
    if (source) {
      const badge = document.createElement("span");
      badge.className = "source";
      const items = events || [];
      const confidences = items.map((event) => Number(event.confidence))
        .filter((value) => Number.isFinite(value));
      const average = confidences.length
        ? confidences.reduce((sum, value) => sum + value, 0) / confidences.length
        : null;
      const methods = Array.from(new Set(items.map((event) => event.method).filter(Boolean)));
      const confirmed = items.filter((event) => event && (event.status === "confirmed" ||
        (event.text != null && event.verified))).length;
      badge.textContent = source + (average == null ? "" : " · c " + average.toFixed(2)) +
        (confirmed ? " · ✓" + confirmed : "");
      if (average != null && average < 0.2) badge.classList.add("low-confidence");
      div.title = source + (methods.length ? "; method: " + methods.join(", ") : "") +
        (average == null ? "" :
          "; mean heuristic confidence " + average.toFixed(3) + " (not a probability)");
      div.appendChild(badge);
    }
    return div;
  }

  function renderLabels() {
    const markerLabels = $("markerLabels");
    const trackLabels = $("trackLabels");
    markerLabels.replaceChildren();
    trackLabels.replaceChildren();
    state.lanes.forEach((lane) => markerLabels.appendChild(
      makeLabel(lane.label, "marker-label", lane.source, lane.events)
    ));
    state.rows.forEach((row) => {
      const label = document.createElement("div");
      label.className = "track-label " + row.kind;
      if (row.kind === "group") {
        const button = document.createElement("button");
        const collapsed = state.collapsedGroups.has(row.group.id);
        button.textContent = collapsed ? "▸" : "▾";
        button.setAttribute("aria-label", (collapsed ? "Expand " : "Collapse ") + row.group.name);
        button.addEventListener("click", () => {
          if (collapsed) state.collapsedGroups.delete(row.group.id);
          else state.collapsedGroups.add(row.group.id);
          refreshTimeline();
        });
        label.appendChild(button);
        const name = document.createElement("span");
        name.textContent = row.group.name;
        label.appendChild(name);
        const meta = document.createElement("span");
        meta.className = "track-meta";
        meta.textContent = String(row.count);
        label.appendChild(meta);
      } else if (row.kind === "prop") {
        const button = document.createElement("button");
        const collapsed = state.collapsedProps.has(row.prop.id);
        button.textContent = collapsed ? "▸" : "▾";
        button.setAttribute("aria-label", (collapsed ? "Expand " : "Collapse ") + row.prop.name);
        button.addEventListener("click", () => {
          if (collapsed) state.collapsedProps.delete(row.prop.id);
          else state.collapsedProps.add(row.prop.id);
          refreshTimeline();
        });
        label.appendChild(button);
        const name = document.createElement("span");
        name.textContent = row.prop.name;
        label.appendChild(name);
        const meta = document.createElement("span");
        meta.className = "track-meta";
        meta.textContent = String(row.prop.channels.length) + " ch";
        label.appendChild(meta);
      } else {
        const name = document.createElement("span");
        name.textContent = "Channel " + (row.channelIndex + 1) + " · r" + row.channel.row +
          " c" + row.channel.col + " · " + row.channel.color;
        label.appendChild(name);
        const meta = document.createElement("span");
        meta.className = "track-meta";
        meta.textContent = String(row.channel.effects.length);
        label.appendChild(meta);
      }
      trackLabels.appendChild(label);
    });
  }

  function setCanvasSize(canvas, width, height) {
    canvas.width = Math.max(1, Math.ceil(width));
    canvas.height = Math.max(1, Math.ceil(height));
    canvas.style.width = Math.max(1, Math.ceil(width)) + "px";
    canvas.style.height = Math.max(1, Math.ceil(height)) + "px";
    return canvas.getContext("2d");
  }

  function getTimelineDurationSeconds() {
    const durations = [
      state.sequence ? state.sequence.durationSeconds : 0,
      state.audioBuffer ? state.audioBuffer.duration : 0,
      state.analysis && state.analysis.audio
        ? Number(state.analysis.audio.duration_seconds) || 0
        : 0,
      state.vocals ? Number(state.vocals.duration_seconds) || 0 : 0
    ];
    return Math.max(...durations);
  }

  function drawRuler(width, duration, pps) {
    const canvas = $("rulerCanvas");
    const ctx = setCanvasSize(canvas, width, RULER_HEIGHT);
    ctx.fillStyle = "#292521";
    ctx.fillRect(0, 0, width, RULER_HEIGHT);
    const step = pps < 14 ? 10 : pps < 25 ? 5 : 2;
    ctx.font = "10px Segoe UI, sans-serif";
    for (let second = 0; second <= duration; second += 1) {
      const x = second * pps;
      const major = second % step === 0;
      ctx.strokeStyle = major ? "#72695e" : "#413b35";
      ctx.beginPath();
      ctx.moveTo(Math.floor(x) + .5, major ? 13 : 25);
      ctx.lineTo(Math.floor(x) + .5, RULER_HEIGHT);
      ctx.stroke();
      if (major) {
        ctx.fillStyle = "#bdb3a6";
        ctx.fillText(formatTime(second), x + 4, 11);
      }
    }
    const bars = state.sequence.timingGrids.find((grid) => /^bars?$/i.test(grid.name));
    const downbeats = state.analysis && state.analysis.analysis &&
      state.analysis.analysis.downbeats;
    if (!bars && downbeats && downbeats.length) {
      // No native bar grid: number the estimated bars, drawn dimmer as estimates.
      ctx.fillStyle = "#8a7bb0";
      downbeats.forEach((event, index) => {
        const x = Number(event.time) * pps;
        ctx.fillRect(x, 17, 1, RULER_HEIGHT - 17);
        if (pps >= 10 || index % 4 === 0) ctx.fillText("~" + (index + 1), x + 3, 27);
      });
    }
    if (bars) {
      ctx.fillStyle = "#b59ce9";
      timingGridMarks(bars).forEach((cs, index) => {
        const x = (cs / 100) * pps;
        ctx.fillRect(x, 15, 1, RULER_HEIGHT - 15);
        if (pps >= 16 && index % 1 === 0) ctx.fillText(String(index + 1), x + 3, 27);
      });
    }
  }

  function buildWaveformPeaks(buffer) {
    const bucketSize = 128;
    const channelData = Array.from({ length: buffer.numberOfChannels }, (_, index) =>
      buffer.getChannelData(index));
    const bucketCount = Math.ceil(buffer.length / bucketSize);
    const channels = channelData.map(() => ({
      minimum: new Float32Array(bucketCount),
      maximum: new Float32Array(bucketCount)
    }));
    for (let channel = 0; channel < channelData.length; channel++) {
      const samples = channelData[channel];
      for (let bucket = 0; bucket < bucketCount; bucket++) {
        const start = bucket * bucketSize;
        const end = Math.min(buffer.length, start + bucketSize);
        let low = 1;
        let high = -1;
        for (let sample = start; sample < end; sample++) {
          const value = samples[sample];
          if (value < low) low = value;
          if (value > high) high = value;
        }
        channels[channel].minimum[bucket] = low;
        channels[channel].maximum[bucket] = high;
      }
    }
    return { bucketSize, channels };
  }

  function drawWaveform(width, pps) {
    const canvas = $("waveformCanvas");
    const ctx = setCanvasSize(canvas, width, WAVE_HEIGHT);
    ctx.fillStyle = "#1b1916";
    ctx.fillRect(0, 0, width, WAVE_HEIGHT);
    ctx.strokeStyle = "#3a342c";
    ctx.beginPath();
    ctx.moveTo(0, WAVE_HEIGHT / 2);
    ctx.lineTo(width, WAVE_HEIGHT / 2);
    ctx.stroke();
    if (!state.audioBuffer) {
      ctx.fillStyle = "#857a6c";
      ctx.font = "11px Segoe UI, sans-serif";
      ctx.fillText("Open the matching audio file to render its real waveform", 16, 25);
      return;
    }
    const sampleRate = state.audioBuffer.sampleRate;
    const peaks = state.waveformPeaks;
    if (!peaks) return;
    const channelCount = peaks.channels.length;
    const channelHeight = WAVE_HEIGHT / channelCount;
    for (let channelIndex = 0; channelIndex < channelCount; channelIndex++) {
      const channelPeaks = peaks.channels[channelIndex];
      const center = channelIndex * channelHeight + channelHeight / 2;
      ctx.strokeStyle = channelIndex === 0 ? "#f2c46d" : "#d9a54a";
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let x = 0; x < width; x++) {
        const from = Math.floor((x / pps) * sampleRate);
        if (from >= state.audioBuffer.length) break;
        const to = Math.min(state.audioBuffer.length, Math.max(from + 1,
          Math.floor(((x + 1) / pps) * sampleRate)));
        const firstBucket = Math.floor(from / peaks.bucketSize);
        const lastBucket = Math.min(channelPeaks.minimum.length - 1,
          Math.floor((to - 1) / peaks.bucketSize));
        let min = 1;
        let max = -1;
        for (let bucket = firstBucket; bucket <= lastBucket; bucket++) {
          min = Math.min(min, channelPeaks.minimum[bucket]);
          max = Math.max(max, channelPeaks.maximum[bucket]);
        }
        const y1 = center - max * (channelHeight * .43);
        const y2 = center - min * (channelHeight * .43);
        ctx.moveTo(x + .5, y1);
        ctx.lineTo(x + .5, y2);
      }
      ctx.stroke();
    }
    if (channelCount === 2) {
      ctx.strokeStyle = "#3a342c";
      ctx.beginPath();
      ctx.moveTo(0, WAVE_HEIGHT / 2);
      ctx.lineTo(width, WAVE_HEIGHT / 2);
      ctx.stroke();
    }
    ctx.fillStyle = "rgba(242, 180, 65, .05)";
    ctx.fillRect(0, 0, width, WAVE_HEIGHT);
    ctx.fillStyle = "#d9b98a";
    ctx.font = "9px Segoe UI, sans-serif";
    ctx.fillText(formatTime(state.audioBuffer.duration) + ", " +
      (state.audioBuffer.numberOfChannels > 1 ? "stereo" : "mono"), 10, 12);
  }

  function drawMarkers(width, pps) {
    const canvas = $("markersCanvas");
    const height = Math.max(MARKER_HEIGHT, state.lanes.length * MARKER_HEIGHT);
    const ctx = setCanvasSize(canvas, width, height);
    ctx.fillStyle = "#1d1a17";
    ctx.fillRect(0, 0, width, height);
    const colors = {
      native: "#9a8f80",
      beats: "#54b88f",
      downbeats: "#b28be8",
      onsets: "#d99b56",
      sections: "#4fa9b7",
      phrases: "#8c79c7",
      energy: "#6ca4b7",
      stops: "#d56e70",
      "vocal-regions": "#5ea8d9",
      syllables: "#d48db9",
      tempo: "#e0c35a",
      hits: "#9fd3e6",
      crashes: "#f2e27a",
      lyrics: "#e8b7d8",
      offbeat: "#e8665f"
    };
    state.lanes.forEach((lane, laneIndex) => {
      const y = laneIndex * MARKER_HEIGHT;
      ctx.fillStyle = laneIndex % 2 ? "#1e1b18" : "#181614";
      ctx.fillRect(0, y, width, MARKER_HEIGHT);
      ctx.strokeStyle = "#36312c";
      ctx.beginPath();
      ctx.moveTo(0, y + MARKER_HEIGHT - .5);
      ctx.lineTo(width, y + MARKER_HEIGHT - .5);
      ctx.stroke();
      const color = colors[lane.kind] || "#9a8f80";
      if (lane.kind === "tempo") {
        const values = lane.events.map((item) => Number(item.bpm)).filter(Number.isFinite);
        const low = Math.min(...values);
        const high = Math.max(...values);
        const span = Math.max(1, high - low);
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        lane.events.forEach((item, index) => {
          const px = Number(item.time) * pps;
          const py = y + MARKER_HEIGHT - 4 - ((Number(item.bpm) - low) / span) * (MARKER_HEIGHT - 9);
          if (index === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        });
        ctx.stroke();
        // Label the tempo wherever it settles at a new value.
        ctx.fillStyle = color;
        ctx.font = "9px Segoe UI, sans-serif";
        let lastLabelX = -999;
        let lastBpm = null;
        lane.events.forEach((item) => {
          const bpm = Math.round(Number(item.bpm));
          const px = Number(item.time) * pps;
          if ((lastBpm == null || Math.abs(bpm - lastBpm) >= 3) && px - lastLabelX > 46) {
            ctx.fillText(bpm + " BPM", px + 3, y + 9);
            lastLabelX = px;
            lastBpm = bpm;
          }
        });
        return;
      }
      if (lane.kind === "lyrics") {
        ctx.font = "10px Segoe UI, sans-serif";
        for (const line of lane.events) {
          const x1 = Number(line.start) * pps;
          const x2 = Number(line.end) * pps;
          if (!(x2 > x1)) continue;
          ctx.globalAlpha = 0.22;
          ctx.fillStyle = color;
          ctx.fillRect(x1, y + 3, x2 - x1, MARKER_HEIGHT - 6);
          ctx.globalAlpha = 1;
          const chosen = state.reviewSelection && state.reviewSelection.event === line;
          ctx.strokeStyle = chosen ? "#ffffff" : color;
          ctx.lineWidth = chosen ? 2 : 1;
          ctx.setLineDash(line.verified ? [] : [3, 2]);
          ctx.strokeRect(x1 + .5, y + 3.5, Math.max(1, x2 - x1 - 1), MARKER_HEIGHT - 7);
          ctx.setLineDash([]);
          ctx.lineWidth = 1;
          ctx.fillStyle = "rgba(225, 230, 236, .85)";
          for (const word of line.words || []) {
            ctx.fillRect(Number(word.start) * pps, y + MARKER_HEIGHT - 6, 1, 3);
          }
          ctx.save();
          ctx.beginPath();
          ctx.rect(x1 + 2, y, Math.max(0, x2 - x1 - 4), MARKER_HEIGHT);
          ctx.clip();
          ctx.fillStyle = "#f2e6ee";
          ctx.fillText(line.text, x1 + 4, y + 14);
          ctx.restore();
        }
        drawReviewPreview(ctx, lane, y, pps);
        return;
      }
      if (lane.kind === "energy") {
        const maximum = lane.events.reduce(
          (value, event) => Math.max(value, Number(event.rms) || 0),
          0.000001
        );
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        lane.events.forEach((event, index) => {
          const x = Number(event.time) * pps;
          const value = Math.max(0, Number(event.rms) || 0);
          const pointY = y + MARKER_HEIGHT - 3 - (value / maximum) * (MARKER_HEIGHT - 7);
          if (index === 0) ctx.moveTo(x, pointY);
          else ctx.lineTo(x, pointY);
        });
        ctx.stroke();
        return;
      }
      let laneEvents = lane.events;
      if (lane.kind === "onsets") {
        const strongestByPixel = new Map();
        for (const event of laneEvents) {
          const time = Number(event.time);
          if (!Number.isFinite(time) || time < 0) continue;
          const pixel = Math.floor(time * pps);
          const existing = strongestByPixel.get(pixel);
          if (!existing || (Number(event.strength) || 0) > (Number(existing.strength) || 0)) {
            strongestByPixel.set(pixel, event);
          }
        }
        laneEvents = Array.from(strongestByPixel.values());
      }
      const onsetMaximum = lane.kind === "onsets"
        ? laneEvents.reduce(
          (value, event) => Math.max(value, Number(event.strength) || 0),
          0.000001
        )
        : 1;
      for (const event of laneEvents) {
        const time = event.time != null ? Number(event.time) : Number(event.start);
        if (!Number.isFinite(time) || time < 0) continue;
        const x = time * pps;
        if (lane.kind === "vocal-regions" || lane.kind === "syllables" || lane.kind === "stops") {
          const end = lane.kind === "stops"
            ? time + Number(event.silence_duration)
            : Number(event.end);
          if (Number.isFinite(end) && end > time) {
            const blockY = lane.kind === "vocal-regions" ? y + 5 : y + 7;
            const blockHeight = lane.kind === "vocal-regions" ? 12 : 8;
            const blockWidth = Math.max(2, (end - time) * pps);
            const strength = lane.kind === "syllables"
              ? Math.max(0.2, Math.min(1, Number(event.strength) || 0.2))
              : 1;
            ctx.globalAlpha = lane.kind === "syllables" ? 0.25 + strength * 0.65 : 0.3;
            ctx.fillStyle = color;
            ctx.fillRect(x, blockY, blockWidth, blockHeight);
            ctx.globalAlpha = 1;
            ctx.strokeStyle = color;
            ctx.strokeRect(x, blockY, blockWidth, blockHeight);
            if (lane.kind === "syllables") {
              ctx.strokeStyle = "rgba(245, 224, 238, .85)";
              ctx.beginPath();
              ctx.moveTo(Math.floor(x) + .5, y + 3);
              ctx.lineTo(Math.floor(x) + .5, y + MARKER_HEIGHT - 3);
              ctx.stroke();
            }
          }
        } else {
          const rawConfidence = Number(event.confidence);
          const confidence = Number.isFinite(rawConfidence)
            ? Math.max(0, Math.min(1, rawConfidence))
            : 0.35;
          const lowConfidence = (lane.kind === "beats" || lane.kind === "downbeats") &&
            confidence < 0.2;
          ctx.save();
          if (lane.kind === "onsets") {
            const strength = Math.max(0, Number(event.strength) || 0);
            ctx.globalAlpha = 0.25 + 0.65 * strength / onsetMaximum;
          } else if (lane.kind === "beats" || lane.kind === "downbeats") {
            ctx.globalAlpha = 0.12 + 0.58 * confidence;
          } else {
            ctx.globalAlpha = 0.8;
          }
          ctx.strokeStyle = color;
          ctx.lineWidth = lane.kind === "downbeats" || lane.kind === "crashes" ? 2 : 1;
          ctx.setLineDash(lowConfidence ? [2, 3] : []);
          ctx.beginPath();
          ctx.moveTo(Math.floor(x) + .5, y + (lane.kind === "onsets" ? 10 : 2));
          ctx.lineTo(Math.floor(x) + .5, y + MARKER_HEIGHT - 3);
          ctx.stroke();
          ctx.restore();
          drawMarkerStatus(ctx, lane, event, x, y);
        }
      }
      drawReviewPreview(ctx, lane, y, pps);
    });
  }

  // Confirmed markers get a filled diamond, fitted ones a hollow one; the selected
  // marker is white; sections show their part name.
  function drawMarkerStatus(ctx, lane, event, x, y) {
    const status = event.status;
    const chosen = state.reviewSelection && state.reviewSelection.event === event;
    if (chosen) {
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(Math.floor(x) - 1, y + 1, 3, MARKER_HEIGHT - 3);
    }
    if (status === "confirmed" || status === "fitted") {
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(x, y + 1);
      ctx.lineTo(x + 3.5, y + 4.5);
      ctx.lineTo(x, y + 8);
      ctx.lineTo(x - 3.5, y + 4.5);
      ctx.closePath();
      if (status === "confirmed") {
        ctx.fillStyle = "#f4f7fa";
        ctx.fill();
      } else {
        ctx.strokeStyle = "#f4f7fa";
        ctx.lineWidth = 1;
        ctx.stroke();
      }
      ctx.restore();
    }
    if (lane.kind === "sections" && event.label) {
      ctx.fillStyle = "#fff0d6";
      ctx.font = "9px Segoe UI, sans-serif";
      ctx.fillText(event.label, x + 6, y + 14);
    }
  }

  function drawReviewPreview(ctx, lane, y, pps) {
    const drag = state.reviewDrag;
    if (!drag || drag.preview == null || drag.hit.lane.kind !== lane.kind) return;
    ctx.save();
    ctx.strokeStyle = "#ffffff";
    ctx.fillStyle = "rgba(255, 255, 255, .25)";
    ctx.setLineDash([3, 2]);
    const event = drag.hit.event;
    if (event.text != null) {
      let start = Number(event.start);
      let end = Number(event.end);
      if (drag.hit.edge === "start") start = drag.preview;
      else if (drag.hit.edge === "end") end = drag.preview;
      else {
        end = drag.preview + (end - start);
        start = drag.preview;
      }
      ctx.fillRect(start * pps, y + 3, Math.max(1, (end - start) * pps), MARKER_HEIGHT - 6);
      ctx.strokeRect(start * pps, y + 3, Math.max(1, (end - start) * pps), MARKER_HEIGHT - 6);
    } else {
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(drag.preview * pps, y + 1);
      ctx.lineTo(drag.preview * pps, y + MARKER_HEIGHT - 2);
      ctx.stroke();
    }
    ctx.restore();
  }

  function effectColor(effect) {
    if (effect.type === "TWINKLE") return "#a17ce0";
    if (effect.type === "SHIMMER") return "#d79a4e";
    if (effect.type === "INTENSITY") return "#419fc7";
    return "#968b7f";
  }

  function drawTracks(width, pps) {
    const canvas = $("tracksCanvas");
    const height = Math.max(ROW_HEIGHT, state.rows.length * ROW_HEIGHT);
    const ctx = setCanvasSize(canvas, width, height);
    ctx.fillStyle = "#1a1815";
    ctx.fillRect(0, 0, width, height);

    state.rows.forEach((row, index) => {
      const y = index * ROW_HEIGHT;
      if (row.kind === "group") ctx.fillStyle = "#2a2723";
      else if (row.kind === "prop") ctx.fillStyle = "#24211e";
      else ctx.fillStyle = index % 2 ? "#181614" : "#1b1916";
      ctx.fillRect(0, y, width, ROW_HEIGHT);
      ctx.strokeStyle = "#302c28";
      ctx.beginPath();
      ctx.moveTo(0, y + ROW_HEIGHT - .5);
      ctx.lineTo(width, y + ROW_HEIGHT - .5);
      ctx.stroke();
    });

    for (let second = 0; second <= getTimelineDurationSeconds(); second++) {
      const x = second * pps;
      ctx.strokeStyle = second % 5 === 0 ? "#3c3731" : "#2a2622";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(Math.floor(x) + .5, 0);
      ctx.lineTo(Math.floor(x) + .5, height);
      ctx.stroke();
    }

    const bars = state.sequence.timingGrids.find((grid) => /^bars?$/i.test(grid.name));
    const downbeats = state.analysis && state.analysis.analysis &&
      state.analysis.analysis.downbeats;
    if (!bars && downbeats && downbeats.length) {
      // No native bar grid: number the estimated bars, drawn dimmer as estimates.
      ctx.fillStyle = "#8a7bb0";
      downbeats.forEach((event, index) => {
        const x = Number(event.time) * pps;
        ctx.fillRect(x, 17, 1, RULER_HEIGHT - 17);
        if (pps >= 10 || index % 4 === 0) ctx.fillText("~" + (index + 1), x + 3, 27);
      });
    }
    if (bars) {
      ctx.strokeStyle = "rgba(176, 140, 230, .23)";
      timingGridMarks(bars).forEach((cs) => {
        const x = (cs / 100) * pps;
        ctx.beginPath();
        ctx.moveTo(Math.floor(x) + .5, 0);
        ctx.lineTo(Math.floor(x) + .5, height);
        ctx.stroke();
      });
    }

    const beatGrid = state.sequence.timingGrids.find((grid) => /^beats?$/i.test(grid.name));
    const analysis = state.analysis && state.analysis.analysis;
    if (beatGrid) {
      ctx.strokeStyle = "rgba(84, 184, 143, .12)";
      timingGridMarks(beatGrid).forEach((cs) => {
        const x = (cs / 100) * pps;
        ctx.beginPath();
        ctx.moveTo(Math.floor(x) + .5, 0);
        ctx.lineTo(Math.floor(x) + .5, height);
        ctx.stroke();
      });
    } else if (analysis && Array.isArray(analysis.beats)) {
      ctx.strokeStyle = "rgba(84, 184, 143, .10)";
      analysis.beats.forEach((event) => {
        const x = Number(event.time) * pps;
        ctx.beginPath();
        ctx.moveTo(Math.floor(x) + .5, 0);
        ctx.lineTo(Math.floor(x) + .5, height);
        ctx.stroke();
      });
    }

    if (!bars && analysis && Array.isArray(analysis.downbeats)) {
      ctx.strokeStyle = "rgba(178, 139, 232, .17)";
      analysis.downbeats.forEach((event) => {
        const x = Number(event.time) * pps;
        ctx.beginPath();
        ctx.moveTo(Math.floor(x) + .5, 0);
        ctx.lineTo(Math.floor(x) + .5, height);
        ctx.stroke();
      });
    }

    const preview = state.drag && state.drag.preview;
    state.rows.forEach((row, index) => {
      if (row.kind !== "channel") return;
      const y = index * ROW_HEIGHT;
      const effects = preview && preview.changes.has(row.channel)
        ? preview.changes.get(row.channel) : row.channel.effects;
      if (row.channel.edited) {
        ctx.fillStyle = "rgba(240, 196, 92, .55)";
        ctx.fillRect(0, y + 1, 3, ROW_HEIGHT - 2);
      }
      for (const effect of effects) {
        const x1 = effect.start / 100 * pps;
        const x2 = effect.end / 100 * pps;
        const blockWidth = Math.max(1.5, x2 - x1);
        const attrs = effect.attributes;
        const startIntensity = Number(attrs.startIntensity != null ? attrs.startIntensity :
          attrs.intensity != null ? attrs.intensity : 100);
        const endIntensity = Number(attrs.endIntensity != null ? attrs.endIntensity :
          attrs.intensity != null ? attrs.intensity : startIntensity);
        const average = Math.max(0, Math.min(100, (startIntensity + endIntensity) / 2));
        ctx.globalAlpha = .28 + .72 * average / 100;
        if (effect.type === "INTENSITY" && startIntensity !== endIntensity) {
          const gradient = ctx.createLinearGradient(x1, 0, x2, 0);
          gradient.addColorStop(0, "#317fa8");
          gradient.addColorStop(1, "#8ad0e0");
          ctx.fillStyle = gradient;
        } else {
          ctx.fillStyle = effectColor(effect);
        }
        ctx.fillRect(x1, y + 4, blockWidth, ROW_HEIGHT - 8);
        ctx.globalAlpha = 1;
        if (effect.type === "TWINKLE") {
          ctx.strokeStyle = "rgba(238, 225, 255, .65)";
          ctx.setLineDash([2, 3]);
          ctx.beginPath();
          ctx.moveTo(x1, y + 6);
          ctx.lineTo(x2, y + 6);
          ctx.stroke();
          ctx.setLineDash([]);
        } else if (effect.type === "SHIMMER") {
          ctx.strokeStyle = "rgba(255, 239, 208, .65)";
          ctx.beginPath();
          ctx.moveTo(x1, y + ROW_HEIGHT / 2);
          ctx.lineTo(x2, y + ROW_HEIGHT / 2);
          ctx.stroke();
        }
        if (isSelected(effect) || (preview && preview.selected.has(effect))) {
          ctx.strokeStyle = preview && preview.error ? "#ff6b6b" : "#f3f7fa";
          ctx.lineWidth = 1.5;
          ctx.strokeRect(x1, y + 3, blockWidth, ROW_HEIGHT - 6);
          ctx.lineWidth = 1;
        }
      }
    });
  }
  function updatePlayhead() {
    if (!state.sequence) return;
    const seconds = Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
    const visibleTime = Math.min(seconds, getTimelineDurationSeconds());
    playhead.style.left = (visibleTime * state.pxPerSecond) + "px";
    playhead.style.display = state.audioBuffer ? "block" : "none";
    drawYard(yardSeconds());
  }

  function seekAudio(seconds) {
    if (!state.audioBuffer) return;
    audio.currentTime = Math.max(0, Math.min(seconds, state.audioBuffer.duration));
    updatePlayhead();
  }

  function refreshTimeline() {
    if (!state.sequence) return;
    buildRows();
    buildLanes();
    renderLabels();
    const duration = getTimelineDurationSeconds();
    const contentHeight = RULER_HEIGHT + WAVE_HEIGHT +
      state.lanes.length * MARKER_HEIGHT + state.rows.length * ROW_HEIGHT;
    const maxWidth = Math.max(canvasViewport.clientWidth, Math.min(30000,
      Math.floor(MAX_CANVAS_PIXELS / contentHeight)));
    const maxPps = Math.min(48, maxWidth / duration);
    const minPps = Math.min(1, maxPps);
    state.pxPerSecond = Math.max(minPps, Math.min(maxPps, state.pxPerSecond));
    $("zoomSlider").min = String(minPps);
    $("zoomSlider").max = String(maxPps);
    $("zoomSlider").value = String(state.pxPerSecond);
    const width = Math.max(canvasViewport.clientWidth, Math.ceil(duration * state.pxPerSecond));
    $("canvasContent").style.width = width + "px";
    $("labelsContent").style.height = contentHeight + "px";
    drawRuler(width, duration, state.pxPerSecond);
    drawWaveform(width, state.pxPerSecond);
    drawMarkers(width, state.pxPerSecond);
    drawTracks(width, state.pxPerSecond);
    updatePlayhead();
  }

  function renderSequenceStats() {
    const sequence = state.sequence;
    if (!sequence) return;
    $("sequenceTitle").textContent = sequence.name;
    const subtitle = [sequence.artist, sequence.filename].filter(Boolean).join(" · ");
    $("sequenceSubtitle").textContent = subtitle + (sequence.audioName ? " · S6 audio: " + sequence.audioName : "");
    $("durationStat").textContent = formatTime(sequence.durationSeconds);
    $("propStat").textContent = String(sequence.props.length);
    $("channelStat").textContent = String(sequence.channelCount);
    $("effectStat").textContent = sequence.effectCount.toLocaleString();
    const tempo = state.analysis && state.analysis.analysis && state.analysis.analysis.tempo;
    $("tempoStat").textContent = tempo && tempo.bpm != null ? String(tempo.bpm) : "—";
    $("tempoStat").title = tempo && tempo.bpm != null
      ? "Estimated dominant tempo. Method: " + tempo.method +
        ". Heuristic stability confidence: " + tempo.confidence + " (not a probability)."
      : "No reliable dominant tempo estimate is available.";
  }

  async function loadSequence(file) {
    if (!file) return;
    const requestId = ++state.sequenceRequestId;
    try {
      if (state.audioDecodePending) {
        setBanner("Wait for the selected song to finish loading before replacing the sequence.", "warn");
        return;
      }
      if (file.size > MAX_XML_BYTES) throw new Error("Sequence exceeds the 50 MiB input limit.");
      const xmlText = await file.text();
      if (requestId !== state.sequenceRequestId) return;
      if (state.audioDecodePending) {
        setBanner("Wait for the selected song to finish loading before replacing the sequence.", "warn");
        return;
      }
      if (state.dirty && !window.confirm("Discard the unexported edits to " +
        state.sequence.filename + "?")) return;
      const head = new Uint8Array(await file.slice(0, 3).arrayBuffer());
      if (requestId !== state.sequenceRequestId) return;
      if (state.audioDecodePending) {
        setBanner("Wait for the selected song to finish loading before replacing the sequence.", "warn");
        return;
      }
      openSequenceText(xmlText, file.name, head[0] === 0xEF && head[1] === 0xBB && head[2] === 0xBF);
      setBanner("Loaded " + state.sequence.props.length + " native props, " +
        state.sequence.channelCount + " channels, and " + state.sequence.effectCount.toLocaleString() +
        " effects. Edits stay here until you export a new copy; the source file is never changed.",
        "good");
      if (state.audioBuffer) compareDurations();
    } catch (error) {
      if (requestId !== state.sequenceRequestId) return;
      setBanner("That sequence could not be opened: " + problemText(error) +
        " Choose a .loredit file saved by S6.", "error");
    }
  }

  // Show a sequence from its text: a file the user opened, or a show just generated.
  function openSequenceText(xmlText, name, bom) {
      // A direct/generated open supersedes any file read still in progress.
      state.sequenceRequestId += 1;
      const doc = parseXmlDocument(xmlText);
      state.sequence = parseSequence(doc, name);
      const declaration = xmlText.replace(/^\uFEFF/, "").match(/^<\?xml[^?]*\?>/);
      state.sequence.source = {
        originalXml: xmlText,
        bom: Boolean(bom),
        crlf: xmlText.slice(0, 65536).includes("\r\n"),
        declaration: declaration ? declaration[0] : '<?xml version="1.0" encoding="utf-8"?>',
        spacedEmpty: / \/>/.test(xmlText.slice(0, 65536)),
        trailing: (xmlText.match(/>(\s*)$/) || ["", ""])[1].replace(/\r\n/g, "\n")
      };
      resetEditing();
      state.collapsedGroups.clear();
      state.collapsedProps.clear();
      state.selectedEffect = null;
      $("welcome").classList.add("hidden");
      $("newShow").classList.add("hidden");
      $("editor").classList.remove("hidden");
      renderEditInspector();
      renderSequenceStats();
      refreshTimeline();
  }

  async function probeAudioMetadata(file) {
    const url = URL.createObjectURL(file);
    const probe = document.createElement("audio");
    probe.preload = "metadata";
    try {
      const duration = await new Promise((resolve, reject) => {
        probe.onloadedmetadata = () => resolve(probe.duration);
        probe.onerror = () => reject(new Error("The browser could not read audio metadata."));
        probe.src = url;
        probe.load();
      });
      if (!Number.isFinite(duration) || duration < 2 || duration > 1800) {
        throw new Error("Audio duration must be between 2 seconds and 30 minutes.");
      }
      const estimatedBytes = duration * 48000 * 2 * Float32Array.BYTES_PER_ELEMENT;
      if (estimatedBytes > 512 * 1024 * 1024) {
        throw new Error("Decoded audio would exceed the 512 MiB waveform memory budget.");
      }
      return duration;
    } finally {
      probe.pause();
      probe.removeAttribute("src");
      probe.load();
      URL.revokeObjectURL(url);
    }
  }

  async function decodeWaveform(file, requestId) {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) throw new Error("This browser does not support Web Audio waveform decoding.");
    await probeAudioMetadata(file);
    if (requestId !== state.audioRequestId) return null;
    const context = new AudioContextClass();
    let buffer;
    let peaks;
    let playbackSource;
    try {
      const prefix = new Uint8Array(await file.slice(0, 4).arrayBuffer());
      const hasId3 = prefix.length >= 3 && prefix[0] === 73 && prefix[1] === 68 && prefix[2] === 51;
      const hasMpegSync = prefix.length >= 2 && prefix[0] === 255 && (prefix[1] & 224) === 224;
      const mislabeledMp3 = file.name.toLowerCase().endsWith(".mp4") && (hasId3 || hasMpegSync);
      playbackSource = mislabeledMp3
        ? file.slice(0, file.size, "audio/mpeg")
        : file;
      const audioBytes = await file.arrayBuffer();
      buffer = await context.decodeAudioData(audioBytes);
      if (requestId !== state.audioRequestId) return null;
      if (buffer.duration < 2 || buffer.duration > 1800) {
        throw new Error("Audio duration must be between 2 seconds and 30 minutes.");
      }
      peaks = buildWaveformPeaks(buffer);
    } finally {
      await context.close();
    }
    if (requestId !== state.audioRequestId) return null;
    // Decode into temporary values. Do not disturb the active song until the
    // caller can commit the complete buffer, waveform, and playback URL together.
    return {
      buffer,
      peaks,
      url: URL.createObjectURL(playbackSource),
      duration: buffer.duration,
    };
  }

  function currentMusicDuration() {
    if (state.audioBuffer && Number.isFinite(state.audioBuffer.duration) &&
        state.audioBuffer.duration > 0) return state.audioBuffer.duration;
    const analyzed = state.analysis && Number(state.analysis.audio && state.analysis.audio.duration_seconds);
    return Number.isFinite(analyzed) && analyzed > 0 ? analyzed : null;
  }

  function clampReviewSeconds(seconds) {
    const duration = currentMusicDuration();
    return Math.max(0, Math.min(duration == null ? 1800 : duration, seconds));
  }

  function durationMismatchMessage() {
    if (!state.sequence) return "";
    const messages = [];
    if (state.audioBuffer) {
      const delta = state.audioBuffer.duration - state.sequence.durationSeconds;
      if (Math.abs(delta) > 0.25) {
        const direction = delta > 0 ? "longer" : "shorter";
        messages.push("Selected audio is " + Math.abs(delta).toFixed(2) + " seconds " + direction +
          " than the sequence; the timeline shows the full duration of both.");
      }
    }
    if (state.audioFile && state.sequence.audioName) {
      const expected = state.sequence.audioName.split(/[\\/]/).pop();
      if (expected && expected.toLowerCase() !== state.audioFile.name.toLowerCase()) {
        messages.push("This sequence expects the audio file " + expected + ", but the selected file is " +
          state.audioFile.name + ". Check that you selected the matching recording and that S6 can find it.");
      }
    }
    return messages.join(" ");
  }

  function compareDurations() {
    const message = durationMismatchMessage();
    if (message) setBanner(message + " Check that the selected recording matches this sequence.", "warn");
  }

  async function analyzeSelectedAudio(file, requestId = ++state.audioRequestId) {
    if (!file) return;
    const meter = $("meterSelect").value;
    setBanner("Analyzing the selected audio locally: tempo, beats, downbeats, transients, sections, and pauses…");
    try {
      const payload = await withProgress("analysisBanner", "Sending the song", (key) =>
        callEngine("/api/analyze?beats_per_bar=" + meter + "&progress=" + key, file,
          "application/octet-stream"));
      if (requestId !== state.audioRequestId) return;
      if (state.reviewDirty || state.reviewLoaded) {
        // Never replace reviewed markers with fresh estimates.
        setBanner("Audio loaded. Your music review is kept; the fresh automatic analysis was not " +
          "applied over it.", "good");
        return;
      }
      state.analysis = payload.report;
      renderSequenceStats();
      refreshTimeline();
      const analysis = state.analysis.analysis;
      $("analysisBanner").title = analysis.method + "\n" + analysis.provenance +
        "\nLimitations: " + analysis.limitations.join(" ");
      const bpm = analysis.tempo && analysis.tempo.bpm != null ? analysis.tempo.bpm + " BPM" : "tempo unavailable";
      const warning = payload.warning ? " " + payload.warning : "";
      const mismatch = durationMismatchMessage();
      setBanner("Audio analysis complete: " + bpm + "; " + analysis.beats.length +
        " beat candidates, " + analysis.downbeats.length + " downbeats, " +
        analysis.onsets.length + " transients, " + analysis.section_candidates.length +
        " section candidates. Estimates remain editable/reviewable." + warning +
        (mismatch ? " " + mismatch : ""), mismatch ? "warn" : "good");
    } catch (error) {
      if (requestId !== state.audioRequestId) return;
      const mismatch = durationMismatchMessage();
      setBanner("Waveform loaded. Automatic analysis unavailable: " +
        problemText(error) + " You can still edit, or load a saved analysis file." +
        (mismatch ? " " + mismatch : ""), "warn");
    }
  }

  async function loadAudio(file, presetAnalysis, reviewAlreadyConfirmed = false) {
    if (!file) return;
    if (file.size <= 0 || file.size > MAX_AUDIO_BYTES) {
      setBanner("The song file is empty, or larger than the 200 MB the program accepts.", "error");
      return;
    }
    if (!reviewAlreadyConfirmed && state.reviewDirty &&
        !window.confirm("Replace the unsaved music review?")) return;
    const requestId = ++state.audioRequestId;
    state.audioDecodePending = true;
    setStepEnabled();
    state.analysisRequestId += 1;
    state.lyricRequestId += 1;
    state.vocalRequestId += 1;
    let decoded;
    try {
      decoded = await decodeWaveform(file, requestId);
    } catch (error) {
      if (requestId !== state.audioRequestId) return;
      state.audioDecodePending = false;
      setStepEnabled();
      setBanner("That song could not be played here: " + problemText(error) +
        (state.audioFile ? " Your previous audio and music review are still loaded." : ""), "error");
      $("audioFile").value = "";
      return;
    }
    if (requestId !== state.audioRequestId || !decoded) {
      if (decoded && decoded.url) URL.revokeObjectURL(decoded.url);
      return;
    }
    state.audioDecodePending = false;
    setStepEnabled();

    // Commit the replacement only after the complete audio decode has succeeded.
    const previousUrl = state.audioUrl;
    audio.pause();
    state.audioFile = file;
    state.audioBuffer = decoded.buffer;
    state.waveformPeaks = decoded.peaks;
    state.audioUrl = decoded.url;
    state.analysis = presetAnalysis || null;
    state.vocals = null;
    state.lyrics = null;
    state.reviewDirty = false;
    state.reviewLoaded = false;
    state.reviewSaved = false;
    state.reviewSelection = null;
    captureReviewBaseline();
    if (previousUrl) URL.revokeObjectURL(previousUrl);
    audio.src = state.audioUrl;
    audio.load();
    $("playButton").disabled = false;
    $("stopButton").disabled = false;
    $("playButton").textContent = "▶";
    $("analysisBanner").title = "";
    if (state.sequence) {
      renderSequenceStats();
      refreshTimeline();
    }
    compareDurations();

    if (presetAnalysis) {
      // Already analyzed while building the show: use that, do not run it again.
      return;
    }
    setBanner("Waveform decoded from the selected audio (" + formatTime(decoded.duration) +
      "). Starting local musical analysis…", "good");
    await analyzeSelectedAudio(file, requestId);
  }

  async function loadAnalysis(file) {
    if (!file) return;
    if (state.audioDecodePending) {
      setBanner("Wait for the selected song to finish loading before importing its analysis.", "warn");
      $("analysisFile").value = "";
      return;
    }
    const requestId = ++state.analysisRequestId;
    try {
      if (file.size > MAX_JSON_BYTES) throw new Error("Analysis JSON exceeds the 5 MiB input limit.");
      const analysisText = await file.text();
      if (requestId !== state.analysisRequestId) return;
      let data = JSON.parse(analysisText);
      if (!data || typeof data !== "object") throw new Error("Analysis JSON must contain an object.");
      let review = null;
      if (data.schema_version === REVIEW_SCHEMA) {
        // A saved music review: the corrected analysis, reviewed lyrics and meter.
        review = data;
        if ((review.meter === 3 || review.meter === 4) && show.token &&
            $("meterSelect").value !== String(review.meter) &&
            (show.audioPending || show.requirementsPending || show.displayPending ||
             show.generationPending || show.batchRunning || show.batchZipPending || show.testPending)) {
          throw new Error("Wait for the current New Show operation to finish before loading a review with a different meter.");
        }
        data = review.analysis;
        if (!data || typeof data !== "object") throw new Error("The music review has no analysis.");
        if (review.lyrics != null) {
          checkLyrics(review.lyrics);
          const duration = state.audioBuffer && Number.isFinite(state.audioBuffer.duration)
            ? state.audioBuffer.duration : Number(data.audio && data.audio.duration_seconds);
          if (Number.isFinite(duration) && duration > 0 &&
              review.lyrics.lines.some((line) => line.end > duration + 1)) {
            throw new Error("The saved review's lyrics extend beyond the selected song.");
          }
        }
      }
      const analysis = data.analysis;
      const currentDuration = state.audioBuffer && Number.isFinite(state.audioBuffer.duration)
        ? state.audioBuffer.duration : null;
      const incomingDuration = Number(data.audio && data.audio.duration_seconds);
      if (currentDuration != null && Math.abs(incomingDuration - currentDuration) > 1) {
        throw new Error("This analysis is for a different-length recording. Choose the analysis that matches the selected song.");
      }
      const analyzedName = data.audio && typeof data.audio.file_name === "string"
        ? data.audio.file_name.split(/[\\/]/).pop() : "";
      if (state.audioFile && analyzedName &&
          analyzedName.toLowerCase() !== state.audioFile.name.toLowerCase() &&
          !window.confirm("This analysis was made from " + analyzedName + ", but the selected audio is " +
            state.audioFile.name + ". They may be different recordings. Load this analysis anyway?")) {
        setBanner("Kept the current analysis; the selected analysis file name did not match the song.", "warn");
        return;
      }
      const requiredArrays = ["beats", "downbeats", "onsets", "energy",
        "phrase_boundaries", "section_candidates", "hard_stops"];
      if (data.schema_version !== "2.0" || !analysis ||
          !data.audio || !Number.isFinite(Number(data.audio.duration_seconds)) ||
          Number(data.audio.duration_seconds) <= 0 || Number(data.audio.duration_seconds) > 1800 ||
          !analysis.tempo || !Array.isArray(analysis.limitations) ||
          typeof analysis.method !== "string" || typeof analysis.provenance !== "string" ||
          requiredArrays.some((key) => !Array.isArray(analysis[key]))) {
        throw new Error("Expected a complete audio-analysis v2.0 JSON report.");
      }
      for (const key of requiredArrays) {
        if (analysis[key].length > 100000) throw new Error("Analysis lane " + key + " exceeds 100,000 events.");
        for (const event of analysis[key]) {
          if (!event || typeof event !== "object") {
            throw new Error("Analysis lane " + key + " contains an invalid event.");
          }
          const time = Number(event.time);
          if (!Number.isFinite(time) || time < 0 || time > Number(data.audio.duration_seconds) + 1) {
            throw new Error("Analysis lane " + key + " contains an invalid timestamp.");
          }
        }
      }
      const discardUnsavedReview = state.reviewDirty;
      if (discardUnsavedReview && !window.confirm("Replace the unsaved music review?")) return;
      state.audioRequestId += 1; // A valid imported analysis supersedes in-flight auto-analysis.
      if (review || discardUnsavedReview) state.lyricRequestId += 1;
      state.analysis = data;
      state.reviewLoaded = Boolean(review);
      state.reviewSaved = Boolean(review);
      state.reviewDirty = false;
      state.reviewSelection = null;
      if (review) {
        state.lyrics = review.lyrics != null ? review.lyrics : null;
        if (review.meter === 3 || review.meter === 4) {
          const previousMeter = $("meterSelect").value;
          const nextMeter = String(review.meter);
          $("meterSelect").value = nextMeter;
          if (previousMeter !== nextMeter && show.token) {
            invalidateGeneratedResult();
            if (show.batchReady && show.batchConfig !== currentBatchConfig()) {
              show.batchReady = false;
              $("saveBatch").disabled = true;
              showMessage("batchStatus", "Meter changed. Rebuild the playlist before saving it.", "warn");
            }
            if (show.audioFile) chooseSong(show.audioFile);
            else setStepEnabled();
          }
        }
      } else if (discardUnsavedReview) {
        state.lyrics = null;
      }
      renderSequenceStats();
      refreshTimeline();
      updateEditControls();
      $("analysisBanner").title = data.analysis.method + "\n" + data.analysis.provenance +
        "\nLimitations: " + data.analysis.limitations.join(" ");
      captureReviewBaseline();
      if (review) {
        const counts = reviewCounts();
        setBanner("Loaded music review: " + counts.confirmed + " confirmed and " + counts.fitted +
          " fitted markers, " + counts.lyric_lines_confirmed + " of " + counts.lyric_lines +
          " lyric lines confirmed.", "good");
      } else {
        setBanner("Loaded saved analysis. Beat, downbeat, onset, section, and silence markers are labeled as estimates.", "good");
      }
    } catch (error) {
      if (requestId !== state.analysisRequestId) return;
      setBanner("That analysis file could not be loaded: " + problemText(error) +
        " Choose a .analysis.json or .review.json file made by this program.", "error");
    }
  }

  async function loadVocals(file) {
    if (!file) return;
    if (state.audioDecodePending) {
      setBanner("Wait for the selected song to finish loading before importing its vocal report.", "warn");
      $("vocalsFile").value = "";
      return;
    }
    const requestId = ++state.vocalRequestId;
    try {
      if (file.size > MAX_JSON_BYTES) throw new Error("Vocal JSON exceeds the 5 MiB input limit.");
      const vocalsText = await file.text();
      if (requestId !== state.vocalRequestId) return;
      const data = JSON.parse(vocalsText);
      if (!data || typeof data !== "object") throw new Error("Vocal JSON must contain an object.");
      const duration = Number(data.duration_seconds);
      const currentDuration = currentMusicDuration();
      if (currentDuration != null && Math.abs(duration - currentDuration) > 1) {
        throw new Error("This vocal report is for a different-length recording. Choose the report that matches the selected song.");
      }
      if (data.schema_version !== "vocals-1.0" || !Number.isFinite(duration) ||
          duration <= 0 || duration > 1800 || !Array.isArray(data.limitations) ||
          typeof data.method !== "string" ||
          !Array.isArray(data.regions) || !Array.isArray(data.syllables) ||
          data.regions.length > 100000 || data.syllables.length > 100000) {
        throw new Error("Expected a complete vocals-1.0 JSON report.");
      }
      for (const event of data.regions.concat(data.syllables)) {
        if (!event || typeof event !== "object") {
          throw new Error("Vocal report contains an invalid event.");
        }
        const start = Number(event.start);
        const end = Number(event.end);
        if (!Number.isFinite(start) || !Number.isFinite(end) ||
            start < 0 || end <= start || end > duration + 1) {
          throw new Error("Vocal report contains an invalid event boundary.");
        }
      }
      state.vocals = data;
      refreshTimeline();
      $("analysisBanner").title = data.method + "\nLimitations: " + data.limitations.join(" ");
      setBanner("Loaded vocal regions and syllable candidates. This analysis is heuristic and does not identify words or lyrics.", "good");
    } catch (error) {
      if (requestId !== state.vocalRequestId) return;
      setBanner("That vocal file could not be loaded: " + problemText(error), "error");
    }
  }

  function parseLyricsText(text, name) {
    const lines = [];
    const lrc = /\[(\d{1,3}):(\d{1,2}(?:\.\d{1,3})?)\]/g;
    const cue = /(?:(\d+):)?(\d{1,2}):(\d{1,2})[.,](\d{1,3})\s*-->\s*(?:(\d+):)?(\d{1,2}):(\d{1,2})[.,](\d{1,3})/;
    const toSeconds = (h, m, s, f) => Number(h || 0) * 3600 + Number(m) * 60 + Number(s) +
      Number(String(f).padEnd(3, "0").slice(0, 3)) / 1000;
    if (lrc.test(text)) {
      for (const raw of text.split(/\r?\n/)) {
        const stamps = Array.from(raw.matchAll(/\[(\d{1,3}):(\d{1,2}(?:\.\d{1,3})?)\]/g));
        const words = raw.replace(/\[[^\]]*\]/g, "").trim();
        for (const stamp of stamps) {
          if (words) lines.push({ start: Number(stamp[1]) * 60 + Number(stamp[2]), end: null, text: words });
        }
      }
    } else {
      for (const block of text.replace(/\r\n/g, "\n").split(/\n\s*\n/)) {
        const match = block.match(cue);
        if (!match) continue;
        const after = block.slice(match.index + match[0].length).trim().split("\n");
        const words = after.map((line) => line.replace(/<[^>]+>/g, "").trim()).join(" ").trim();
        if (words) lines.push({ start: toSeconds(match[1], match[2], match[3], match[4]),
          end: toSeconds(match[5], match[6], match[7], match[8]), text: words });
      }
    }
    if (!lines.length) throw new Error(name + ": no LRC time tags or SRT/VTT cues found.");
    lines.sort((a, b) => a.start - b.start);
    lines.forEach((line) => {
      if (line.end == null) {
        const next = lines.find((candidate) => candidate.start > line.start + 0.001);
        line.end = next ? next.start : Math.min(1801, line.start + 4);
      }
      line.verified = true;
      line.words = [];
    });
    return { schema_version: "lyrics-1.0", source: "imported", lines };
  }

  function checkLyrics(data) {
    if (!data || data.schema_version !== "lyrics-1.0" || !Array.isArray(data.lines) ||
        data.lines.length > 5000) throw new Error("Expected a lyrics-1.0 JSON document.");
    for (const line of data.lines) {
      const start = line && line.start;
      const end = line && line.end;
      if (!line || typeof line.text !== "string" || typeof start !== "number" ||
          !Number.isFinite(start) || typeof end !== "number" || !Number.isFinite(end) ||
          start < 0 || end <= start || end > 1801 ||
          (line.words != null && !Array.isArray(line.words)) ||
          (line.words && line.words.length > 1000) ||
          (line.verified != null && typeof line.verified !== "boolean")) {
        throw new Error("Lyrics contain an invalid line.");
      }
      for (const word of line.words || []) {
        const wordStart = word && word.start;
        const wordEnd = word && word.end;
        if (!word || typeof word !== "object" || typeof word.text !== "string" ||
            !word.text.trim() || typeof wordStart !== "number" || !Number.isFinite(wordStart) ||
            typeof wordEnd !== "number" || !Number.isFinite(wordEnd) ||
            wordStart < start || wordEnd <= wordStart || wordEnd > end + 0.05 ||
            (word.confidence != null && (typeof word.confidence !== "number" ||
              !Number.isFinite(word.confidence) || word.confidence < 0 || word.confidence > 1)) ||
            (word.verified != null && typeof word.verified !== "boolean")) {
          throw new Error("Lyrics contain an invalid word event.");
        }
      }
    }
  }

  async function loadLyrics(file) {
    if (!file) return;
    if (state.audioDecodePending) {
      setBanner("Wait for the selected song to finish loading before importing its lyrics.", "warn");
      $("lyricsFile").value = "";
      return;
    }
    const requestId = ++state.lyricRequestId;
    try {
      if (file.size > MAX_JSON_BYTES) throw new Error("Lyrics file exceeds the 5 MiB input limit.");
      const text = await file.text();
      if (requestId !== state.lyricRequestId) return;
      let data;
      if (/\.json$/i.test(file.name)) {
        data = JSON.parse(text);
      } else {
        data = parseLyricsText(text, file.name);
      }
      checkLyrics(data);
      const duration = currentMusicDuration();
      if (duration != null && data.lines.some((line) => line.end > duration + 1)) {
        throw new Error("These lyrics extend beyond the selected song. Choose the matching lyrics file.");
      }
      if (state.reviewDirty && !window.confirm("Replace the unsaved music review?")) return;
      state.lyrics = data;
      state.reviewSelection = null;
      state.reviewDirty = reviewHasChanges();
      refreshTimeline();
      updateEditControls();
      setBanner(data.source === "transcribed"
        ? "Loaded " + data.lines.length + " transcribed lyric lines. They are unverified: speech recognition mishears sung words. Dashed outlines mark unverified lines."
        : "Loaded " + data.lines.length + " lyric lines from " + file.name + ".", "good");
    } catch (error) {
      if (requestId !== state.lyricRequestId) return;
      setBanner("Those lyrics could not be loaded: " + problemText(error) +
        " Lyrics can be LRC, SRT or VTT files.", "error");
    }
  }

  function seekFromPointer(event, canvas) {
    if (!state.sequence) return;
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const seconds = Math.max(0, Math.min(getTimelineDurationSeconds(), x / state.pxPerSecond));
    seekAudio(seconds);
  }

  function syncScroll() {
    labelsViewport.scrollTop = canvasViewport.scrollTop;
    updatePlayhead();
  }

  function tickPlayback() {
    updatePlayhead();
    if (!audio.paused && !audio.ended) state.animationFrame = requestAnimationFrame(tickPlayback);
  }

  // ---------------------------------------------------------------------------
  // Effect editing. Every change goes through applyChanges(), which checks the
  // result (no overlaps, no zero-length effects, nothing past the end) and records
  // the channels' earlier effect lists so undo can put them back. Effects are
  // never changed in place: an edited effect is a new object.

  const EDITABLE_TYPES = ["INTENSITY", "TWINKLE", "SHIMMER"];
  const SNAP_PIXELS = 8;
  const EDGE_PIXELS = 5;
  const DRAG_THRESHOLD = 3;
  const DEFAULT_LENGTH_CS = 50;
  const MAX_UNDO = 300;

  function resetEditing() {
    state.selection = [];
    state.selectionSet = new Set();
    state.selectedEffect = null;
    state.undo = [];
    state.redo = [];
    state.dirty = false;
    state.exported = false;
    state.baselineEffects = new Map();
    state.editRevision = 0;
    state.exportRequestId += 1;
    state.exportPending = false;
    state.drag = null;
    state.clipboard = null;
    state.cursorCs = 0;
    state.channelInfo = new Map();
    for (const prop of state.sequence.props) {
      prop.channels.forEach((channel, index) => {
        state.channelInfo.set(channel, { prop, index });
        state.baselineEffects.set(channel, channel.effects);
      });
    }
    updateEditControls();
  }

  function isSelected(effect) {
    return Boolean(state.selectionSet && state.selectionSet.has(effect));
  }

  function channelName(channel) {
    const info = state.channelInfo.get(channel);
    return info ? info.prop.name + " channel " + (info.index + 1) : "a channel";
  }

  function sortEffects(effects) {
    return effects.slice().sort((a, b) => a.start - b.start || a.end - b.end);
  }

  // Known attributes first, in the order native files use, then anything else as it was.
  function makeEffect(start, end, attributes) {
    const ordered = { startCentisecond: String(start), endCentisecond: String(end) };
    for (const key of ["intensity", "startIntensity", "endIntensity"]) {
      if (attributes[key] != null) ordered[key] = attributes[key];
    }
    for (const key of Object.keys(attributes)) {
      if (!(key in ordered)) ordered[key] = attributes[key];
    }
    return { start, end, type: ordered.settings || "UNKNOWN", attributes: ordered };
  }

  function withTimes(effect, start, end) {
    return makeEffect(start, end, effect.attributes);
  }

  function checkChannel(channel, effects) {
    const before = new Set(channel.effects);
    const limit = state.sequence.durationCs;
    const active = [];
    for (const effect of effects) {
      if (!before.has(effect)) {
        if (effect.start < 0) return "an effect would start before the song";
        if (effect.end <= effect.start) return "an effect would have no length";
        if (effect.end > limit) return "an effect would run past the end of the sequence";
      }
      // Compare with every active interval so nested source overlaps cannot hide
      // a newly introduced overlap.
      for (let index = active.length - 1; index >= 0; index--) {
        if (active[index].end <= effect.start) active.splice(index, 1);
      }
      if (active.some((previous) => !(before.has(previous) && before.has(effect)))) {
        return "effects would overlap on " + channelName(channel);
      }
      active.push(effect);
    }
    return null;
  }

  function checkChanges(changes) {
    for (const [channel, effects] of changes) {
      const sorted = sortEffects(effects);
      changes.set(channel, sorted);
      const problem = checkChannel(channel, sorted);
      if (problem) return problem;
    }
    return null;
  }

  function setSelection(items) {
    if (items.length && state.reviewSelection) {
      state.reviewSelection = null;
      drawMarkers(Number($("markersCanvas").width), state.pxPerSecond);
    }
    state.selection = items;
    state.selectionSet = new Set(items.map((item) => item.effect));
    state.selectedEffect = items.length === 1 ? items[0].effect : null;
    renderEditInspector();
    updateEditControls();
  }

  function selectionFrom(channels, wanted) {
    const items = [];
    for (const channel of channels) {
      for (const effect of channel.effects) {
        if (wanted.has(effect)) items.push({ channel, effect });
      }
    }
    return items;
  }

  function perform(command, side) {
    if (command.music) {
      performMusic(command, side);
      afterMusicEdit(null);
      return;
    }
    for (const [channel, effects] of command[side]) {
      channel.effects = effects;
      channel.edited = side === "after" ? true : command.wasEdited.get(channel);
    }
    afterEdit();
  }

  function applyChanges(label, changes, selected) {
    if (!changes.size) return false;
    const problem = checkChanges(changes);
    if (problem) {
      setBanner("Not changed: " + problem + ".", "warn");
      drawTracks(Number($("tracksCanvas").width), state.pxPerSecond);
      return false;
    }
    const command = { label, before: new Map(), after: changes, wasEdited: new Map() };
    for (const channel of changes.keys()) {
      command.before.set(channel, channel.effects);
      command.wasEdited.set(channel, channel.edited);
    }
    perform(command, "after");
    state.undo.push(command);
    if (state.undo.length > MAX_UNDO) state.undo.shift();
    state.redo = [];
    setSelection(selectionFrom(changes.keys(), new Set(selected || [])));
    setBanner(label + ". Undo with Ctrl+Z.", "good");
    return true;
  }

  function changedEffects(command, side, other) {
    const kept = new Set();
    for (const effects of command[other].values()) effects.forEach((effect) => kept.add(effect));
    const changed = new Set();
    for (const effects of command[side].values()) {
      effects.forEach((effect) => { if (!kept.has(effect)) changed.add(effect); });
    }
    return changed;
  }

  function undoEdit() {
    const command = state.undo.pop();
    if (!command) return;
    perform(command, "before");
    state.redo.push(command);
    if (!command.music) {
      setSelection(selectionFrom(command.before.keys(), changedEffects(command, "before", "after")));
    }
    setBanner("Undid: " + command.label + ".", "good");
  }

  function redoEdit() {
    const command = state.redo.pop();
    if (!command) return;
    perform(command, "after");
    state.undo.push(command);
    if (!command.music) {
      setSelection(selectionFrom(command.after.keys(), changedEffects(command, "after", "before")));
    }
    setBanner("Redid: " + command.label + ".", "good");
  }

  function afterEdit() {
    const sequence = state.sequence;
    let count = 0;
    let edited = 0;
    const types = {};
    for (const prop of sequence.props) {
      for (const channel of prop.channels) {
        count += channel.effects.length;
        if (channel.edited) edited += 1;
        for (const effect of channel.effects) types[effect.type] = (types[effect.type] || 0) + 1;
      }
    }
    sequence.effectCount = count;
    sequence.effectTypes = types;
    state.editedChannels = edited;
    state.syncCheck = null;
    state.editRevision += 1;
    state.dirty = Boolean(sequence.generated && !state.exported) ||
      sequence.props.some((prop) => prop.channels.some((channel) =>
        state.baselineEffects.get(channel) !== channel.effects));
    renderSequenceStats();
    refreshTimeline();
    updateEditControls();
    drawYard(yardSeconds());
  }

  function updateEditControls() {
    const has = state.selection.length > 0;
    const set = (id, enabled) => { const element = $(id); if (element) element.disabled = !enabled; };
    set("undoButton", state.undo.length > 0);
    set("redoButton", state.redo.length > 0);
    set("deleteButton", has);
    set("duplicateButton", has);
    set("exportButton", Boolean(state.sequence) && !state.exportPending);
    set("saveReviewButton", Boolean(state.analysis));
    const exportButton = $("exportButton");
    if (exportButton) {
      exportButton.textContent = state.sequence && state.sequence.generated ? "Save sequence"
        : "Export edited copy";
    }
    const status = $("editStatus");
    if (status) {
      const parts = [];
      if (state.dirty) parts.push("Unexported edits on " + (state.editedChannels || 0) + " channel(s)");
      else if (state.exported) parts.push("Edits exported");
      if (state.reviewDirty) parts.push("unsaved music review");
      else if (state.reviewSaved) parts.push("music review saved");
      status.textContent = !state.sequence ? "" : parts.length ? parts.join(" · ") : "No edits";
      status.classList.toggle("dirty", state.dirty || state.reviewDirty);
      status.title = status.textContent;
    }
  }

  // --- Snapping --------------------------------------------------------------

  function snapEnabled(id) {
    const box = $("snap-" + id);
    return Boolean(box && box.checked);
  }

  function snapCandidates(exclude) {
    const times = [];
    const addEvents = (events) => {
      for (const event of events || []) {
        const time = Number(event.time != null ? event.time : event.start);
        if (Number.isFinite(time)) times.push(Math.round(time * 100));
      }
    };
    const sequence = state.sequence;
    if (snapEnabled("grid")) {
      for (const grid of sequence.timingGrids) {
        for (const cs of timingGridMarks(grid)) times.push(cs);
      }
    }
    const analysis = state.analysis && state.analysis.analysis;
    if (analysis) {
      if (snapEnabled("beats")) addEvents(analysis.beats);
      if (snapEnabled("downbeats")) addEvents(analysis.downbeats);
      if (snapEnabled("onsets")) addEvents(analysis.onsets);
      if (snapEnabled("hits")) {
        addEvents(analysis.high_hits);
        addEvents(analysis.crashes);
      }
    }
    if (snapEnabled("vocal") && state.vocals) addEvents(state.vocals.syllables);
    if (snapEnabled("words") && state.lyrics) {
      for (const line of state.lyrics.lines) {
        times.push(Math.round(line.start * 100));
        for (const word of line.words || []) times.push(Math.round(word.start * 100));
      }
    }
    if (snapEnabled("edges")) {
      for (const prop of sequence.props) {
        for (const channel of prop.channels) {
          for (const effect of channel.effects) {
            if (exclude && exclude.has(effect)) continue;
            times.push(effect.start, effect.end);
          }
        }
      }
    }
    return Float64Array.from(times).sort();
  }

  // The nearest candidate within SNAP_PIXELS, or null.
  function snapTarget(cs, candidates) {
    if (!candidates || !candidates.length) return null;
    let low = 0;
    let high = candidates.length - 1;
    while (low < high) {
      const middle = (low + high) >> 1;
      if (candidates[middle] < cs) low = middle + 1;
      else high = middle;
    }
    let best = null;
    for (const index of [low - 1, low]) {
      if (index >= 0 && index < candidates.length &&
          (best == null || Math.abs(candidates[index] - cs) < Math.abs(best - cs))) {
        best = candidates[index];
      }
    }
    return best != null && Math.abs(best - cs) / 100 * state.pxPerSecond <= SNAP_PIXELS
      ? best : null;
  }

  function snap(cs, candidates, free) {
    if (free) return cs;
    const target = snapTarget(cs, candidates);
    return target == null ? cs : target;
  }

  // --- Edit operations ---------------------------------------------------------

  function groupByChannel(items) {
    const groups = new Map();
    for (const item of items) {
      if (!groups.has(item.channel)) groups.set(item.channel, new Set());
      groups.get(item.channel).add(item.effect);
    }
    return groups;
  }

  function moveChanges(items, delta) {
    const changes = new Map();
    const selected = [];
    for (const [channel, effects] of groupByChannel(items)) {
      changes.set(channel, channel.effects.map((effect) => {
        if (!effects.has(effect)) return effect;
        const moved = withTimes(effect, effect.start + delta, effect.end + delta);
        selected.push(moved);
        return moved;
      }));
    }
    return { changes, selected };
  }

  function trimChanges(item, edge, cs) {
    const effect = item.effect;
    const start = edge === "start" ? Math.min(cs, effect.end - 1) : effect.start;
    const end = edge === "end" ? Math.max(cs, effect.start + 1) : effect.end;
    const trimmed = withTimes(effect, start, end);
    const changes = new Map([[item.channel,
      item.channel.effects.map((other) => other === effect ? trimmed : other)]]);
    return { changes, selected: [trimmed] };
  }

  function newEffect(start, end) {
    return makeEffect(start, end, { intensity: "100", settings: "INTENSITY" });
  }

  function createChanges(channel, start, end) {
    const created = newEffect(start, end);
    return { changes: new Map([[channel, channel.effects.concat([created])]]), selected: [created] };
  }

  function deleteSelection() {
    if (!state.selection.length) return;
    const changes = new Map();
    for (const [channel, effects] of groupByChannel(state.selection)) {
      changes.set(channel, channel.effects.filter((effect) => !effects.has(effect)));
    }
    applyChanges("Deleted " + state.selection.length + " effect(s)", changes, []);
  }

  function addCopies(items, offset, label) {
    const changes = new Map();
    const selected = [];
    for (const item of items) {
      const list = changes.get(item.channel) || item.channel.effects.slice();
      const copy = withTimes(item.effect, item.effect.start + offset, item.effect.end + offset);
      list.push(copy);
      selected.push(copy);
      changes.set(item.channel, list);
    }
    return applyChanges(label, changes, selected);
  }

  function selectionSpan(items) {
    let start = Infinity;
    let end = -Infinity;
    for (const item of items) {
      start = Math.min(start, item.effect.start);
      end = Math.max(end, item.effect.end);
    }
    return { start, end };
  }

  function duplicateSelection() {
    if (!state.selection.length) return;
    const span = selectionSpan(state.selection);
    addCopies(state.selection, span.end - span.start,
      "Duplicated " + state.selection.length + " effect(s)");
  }

  function copySelection() {
    if (!state.selection.length) return false;
    state.clipboard = { items: state.selection.slice(), start: selectionSpan(state.selection).start };
    setBanner("Copied " + state.selection.length + " effect(s). Click a time and press Ctrl+V to paste.",
      "good");
    return true;
  }

  function pasteClipboard() {
    const clip = state.clipboard;
    if (!clip) return;
    const live = clip.items.filter((item) => state.channelInfo.has(item.channel));
    addCopies(live, state.cursorCs - clip.start, "Pasted " + live.length + " effect(s) at " +
      formatCentiseconds(state.cursorCs));
  }

  function nudgeSelection(delta) {
    if (!state.selection.length) return;
    const span = selectionSpan(state.selection);
    if (span.start + delta < 0) return;
    const result = moveChanges(state.selection, delta);
    applyChanges("Nudged " + state.selection.length + " effect(s) " +
      (delta > 0 ? "+" : "") + (delta / 100).toFixed(2) + " s", result.changes, result.selected);
  }

  function setProperties(items, values) {
    const changes = new Map();
    const selected = [];
    for (const item of items) {
      const effect = item.effect;
      const attributes = Object.assign({}, effect.attributes);
      if (values.type && EDITABLE_TYPES.includes(effect.type)) attributes.settings = values.type;
      const type = attributes.settings;
      if (EDITABLE_TYPES.includes(type) && values.intensity) {
        delete attributes.intensity;
        delete attributes.startIntensity;
        delete attributes.endIntensity;
        if (type === "INTENSITY" && values.intensity.fade) {
          attributes.startIntensity = String(values.intensity.start);
          attributes.endIntensity = String(values.intensity.end);
        } else {
          attributes.intensity = String(values.intensity.level);
        }
      }
      const start = values.start != null ? values.start : effect.start;
      const end = values.end != null ? values.end : effect.end;
      const replacement = makeEffect(start, end, attributes);
      const list = changes.get(item.channel) || item.channel.effects.slice();
      list[list.indexOf(effect)] = replacement;
      changes.set(item.channel, list);
      selected.push(replacement);
    }
    return applyChanges("Changed " + items.length + " effect(s)", changes, selected);
  }

  // Move every effect that starts at the flagged lighting change onto the musical
  // moment, and keep each channel continuous: an effect that ended exactly where the
  // moved one started (or would now overlap it) ends at the new time.
  function retimeToMoment(hit) {
    const from = hit.change_cs;
    const to = Math.round(hit.time * 100);
    if (from == null || from === to || !state.sequence) return;
    const changes = new Map();
    const moved = [];
    for (const prop of state.sequence.props) {
      for (const channel of prop.channels) {
        if (!channel.effects.some((item) => item.start === from)) continue;
        const list = [];
        for (const effect of channel.effects) {
          if (effect.start === from) {
            if (to >= effect.end) {
              setBanner("Not changed: the effect on " + channelName(channel) +
                " would have no length.", "warn");
              return;
            }
            const replacement = withTimes(effect, to, effect.end);
            moved.push(replacement);
            list.push(replacement);
          } else if (effect.start < from && (effect.end === from || effect.end > to)) {
            if (to <= effect.start) {
              setBanner("Not changed: the effect before it on " + channelName(channel) +
                " would have no length.", "warn");
              return;
            }
            list.push(withTimes(effect, effect.start, to));
          } else {
            list.push(effect);
          }
        }
        changes.set(channel, list);
      }
    }
    applyChanges("Retimed " + moved.length + " effect(s) from " + formatCentiseconds(from) +
      " to " + formatCentiseconds(to), changes, moved);
  }

  // --- Pointer editing on the tracks ------------------------------------------------

  function trackHit(event) {
    const canvas = $("tracksCanvas");
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const row = state.rows[Math.floor(y / ROW_HEIGHT)];
    const cs = Math.max(0, Math.min(state.sequence.durationCs,
      Math.round(x / state.pxPerSecond * 100)));
    const hit = { row, cs, x, effect: null, edge: null };
    if (!row || row.kind !== "channel") return hit;
    const pps = state.pxPerSecond;
    for (const effect of row.channel.effects) {
      const x1 = effect.start / 100 * pps;
      const x2 = effect.end / 100 * pps;
      if (x < x1 - EDGE_PIXELS || x > x2 + EDGE_PIXELS) continue;
      const inside = x >= x1 && x < x2;
      if (x2 - x1 >= 2 * EDGE_PIXELS + 2 || !inside) {
        if (Math.abs(x - x2) <= EDGE_PIXELS) return Object.assign(hit, { effect, edge: "end" });
        if (Math.abs(x - x1) <= EDGE_PIXELS) return Object.assign(hit, { effect, edge: "start" });
      }
      if (inside) return Object.assign(hit, { effect });
    }
    return hit;
  }

  function handleTrackPointerDown(event) {
    if (!state.sequence || event.button !== 0) return;
    const hit = trackHit(event);
    state.cursorCs = hit.cs;
    if (!state.audioBuffer) drawYard(yardSeconds());
    const additive = event.shiftKey || event.ctrlKey || event.metaKey;
    const base = { startX: event.clientX, moved: false, preview: null };
    if (hit.effect) {
      const item = { channel: hit.row.channel, effect: hit.effect };
      if (hit.edge) {
        setSelection([item]);
        state.drag = Object.assign(base, { mode: "trim", edge: hit.edge, item,
          candidates: snapCandidates(new Set([hit.effect])) });
      } else if (additive) {
        setSelection(isSelected(hit.effect)
          ? state.selection.filter((other) => other.effect !== hit.effect)
          : state.selection.concat([item]));
        return;
      } else {
        const wasSelected = isSelected(hit.effect);
        if (!wasSelected) setSelection([item]);
        state.drag = Object.assign(base, { mode: "move", item, wasSelected, origin: hit.cs,
          items: state.selection.slice(), candidates: snapCandidates(state.selectionSet) });
      }
    } else {
      if (!additive) setSelection([]);
      seekAudio(hit.cs / 100);
      if (hit.row && hit.row.kind === "channel") {
        const candidates = snapCandidates();
        state.drag = Object.assign(base, { mode: "create", channel: hit.row.channel, candidates,
          origin: snap(hit.cs, candidates, event.altKey) });
      }
    }
    if (state.drag) $("tracksCanvas").setPointerCapture(event.pointerId);
  }

  function dragPreview(drag, hit, free) {
    if (drag.mode === "move") {
      let delta = hit.cs - drag.origin;
      const anchor = drag.item.effect;
      if (!free) {
        const startTarget = snapTarget(anchor.start + delta, drag.candidates);
        const endTarget = snapTarget(anchor.end + delta, drag.candidates);
        const startShift = startTarget == null ? null : startTarget - (anchor.start + delta);
        const endShift = endTarget == null ? null : endTarget - (anchor.end + delta);
        if (startShift != null && (endShift == null || Math.abs(startShift) <= Math.abs(endShift))) {
          delta += startShift;
        } else if (endShift != null) {
          delta += endShift;
        }
      }
      const span = selectionSpan(drag.items);
      delta = Math.max(delta, -span.start);
      delta = Math.min(delta, state.sequence.durationCs - span.end);
      const result = moveChanges(drag.items, delta);
      result.label = "Moved " + drag.items.length + " effect(s) " + (delta >= 0 ? "+" : "") +
        (delta / 100).toFixed(2) + " s";
      result.delta = delta;
      return result;
    }
    if (drag.mode === "trim") {
      const result = trimChanges(drag.item, drag.edge, snap(hit.cs, drag.candidates, free));
      const effect = result.selected[0];
      result.label = "Trimmed to " + formatCentiseconds(effect.start) + " → " +
        formatCentiseconds(effect.end);
      return result;
    }
    const other = snap(hit.cs, drag.candidates, free);
    const start = Math.min(drag.origin, other);
    const end = Math.max(drag.origin, other);
    if (end - start < 1) return null;
    const result = createChanges(drag.channel, start, end);
    result.label = "Added an effect " + formatCentiseconds(start) + " → " + formatCentiseconds(end);
    return result;
  }

  function handleTrackPointerMove(event) {
    if (!state.sequence) return;
    const drag = state.drag;
    const canvas = $("tracksCanvas");
    if (!drag) {
      const hit = trackHit(event);
      canvas.style.cursor = hit.edge ? "ew-resize" : hit.effect ? "grab" : "crosshair";
      return;
    }
    if (!drag.moved && Math.abs(event.clientX - drag.startX) < DRAG_THRESHOLD) return;
    drag.moved = true;
    const preview = dragPreview(drag, trackHit(event), event.altKey);
    if (preview) {
      preview.selected = new Set(preview.selected);
      preview.error = checkChanges(preview.changes);
      setBanner(preview.label + (preview.error ? ": not allowed, " + preview.error : "") +
        (event.altKey ? " (snapping off)" : ""), preview.error ? "warn" : "");
    } else {
      setBanner("No valid change at this position; an effect needs a positive length.", "warn");
    }
    drag.preview = preview;
    drawTracks(Number(canvas.width), state.pxPerSecond);
  }

  function handleTrackPointerUp() {
    const drag = state.drag;
    state.drag = null;
    if (!drag) return;
    if (!drag.moved) {
      if (drag.mode === "move" && drag.wasSelected) setSelection([drag.item]);
      drawTracks(Number($("tracksCanvas").width), state.pxPerSecond);
      return;
    }
    const preview = drag.preview;
    if (preview && !preview.error && !(drag.mode === "move" && preview.delta === 0)) {
      applyChanges(preview.label, preview.changes, Array.from(preview.selected));
    } else {
      if (preview && preview.error) setBanner("Not changed: " + preview.error + ".", "warn");
      else if (!preview) setBanner("Not changed: the drag did not produce a valid effect.", "warn");
      else setBanner("No change was made.", "");
      drawTracks(Number($("tracksCanvas").width), state.pxPerSecond);
    }
  }

  function handleTrackDoubleClick(event) {
    if (!state.sequence) return;
    const hit = trackHit(event);
    if (!hit.row || hit.row.kind !== "channel" || hit.effect) return;
    const candidates = snapCandidates();
    const start = snap(hit.cs, candidates, event.altKey);
    let end = start + DEFAULT_LENGTH_CS;
    for (const cs of candidates) {
      if (cs > start + 5) {
        if (cs - start <= 400) end = cs;
        break;
      }
    }
    end = Math.min(end, state.sequence.durationCs);
    const result = createChanges(hit.row.channel, start, end);
    applyChanges("Added an effect " + formatCentiseconds(start) + " → " + formatCentiseconds(end),
      result.changes, result.selected);
  }

  function handleEditKey(event) {
    if (!state.sequence || $("editor").classList.contains("hidden") ||
        !$("viewer").classList.contains("hidden")) return;
    const target = event.target;
    if (target && ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName)) return;
    const mod = event.ctrlKey || event.metaKey;
    if (target && ["BUTTON", "A"].includes(target.tagName) && !mod) return;
    const key = event.key.toLowerCase();
    let handled = true;
    if (mod && key === "z" && !event.shiftKey) undoEdit();
    else if (mod && (key === "y" || (key === "z" && event.shiftKey))) redoEdit();
    else if (mod && key === "d") duplicateSelection();
    else if (mod && key === "c") handled = copySelection();
    else if (mod && key === "x") { if (copySelection()) deleteSelection(); }
    else if (mod && key === "v") pasteClipboard();
    else if (!mod && (key === "delete" || key === "backspace")) {
      if (state.reviewSelection) {
        if (!deleteReviewSelection()) {
          setBanner("Not deleted: the selected music-review marker is no longer available.", "warn");
        }
      } else {
        deleteSelection();
      }
    } else if (!mod && key === "enter" && state.reviewSelection) confirmReviewSelection();
    else if (key === "escape") {
      setSelection([]);
      if (state.reviewSelection) reviewSelect(null);
    }
    else if (!mod && (key === "arrowleft" || key === "arrowright") && state.selection.length) {
      nudgeSelection((key === "arrowleft" ? -1 : 1) * (event.shiftKey ? 10 : 1));
    } else handled = false;
    if (handled) event.preventDefault();
  }

  // --- Inspector ---------------------------------------------------------------

  function field(labelText, input) {
    const label = document.createElement("label");
    label.className = "edit-field";
    const span = document.createElement("span");
    span.textContent = labelText;
    label.append(span, input);
    return label;
  }

  function numberInput(id, value, min, max, step) {
    const input = document.createElement("input");
    input.type = "number";
    input.id = id;
    input.value = String(value);
    input.min = String(min);
    if (max != null) input.max = String(max);
    input.step = String(step);
    return input;
  }

  function intensityOf(effect) {
    const attrs = effect.attributes;
    const level = Number(attrs.intensity != null ? attrs.intensity :
      attrs.endIntensity != null ? Math.max(Number(attrs.startIntensity), Number(attrs.endIntensity))
        : 100);
    return {
      fade: attrs.startIntensity != null && attrs.endIntensity != null,
      level: Number.isFinite(level) ? level : 100,
      start: Number(attrs.startIntensity != null ? attrs.startIntensity : level),
      end: Number(attrs.endIntensity != null ? attrs.endIntensity : level)
    };
  }

  function renderEditInspector() {
    const inspector = $("inspectorContent");
    inspector.replaceChildren();
    const items = state.selection;
    const add = (text, primary) => {
      const item = document.createElement("div");
      if (primary) item.className = "inspector-primary";
      item.textContent = text;
      inspector.appendChild(item);
    };
    if (!items.length) {
      add("Select an effect block to inspect or edit it. Drag to move, drag an edge to trim, " +
        "drag on an empty row to draw, double-click to add one.");
      return;
    }
    const first = items[0].effect;
    if (items.length === 1) {
      const attrs = first.attributes;
      add(channelName(items[0].channel) + " · " + first.type, true);
      add(formatCentiseconds(first.start) + " → " + formatCentiseconds(first.end) + " · " +
        ((first.end - first.start) / 100).toFixed(2) + " s");
      add("Native attributes: " + Object.keys(attrs).map((key) => key + "=" + attrs[key]).join(" · "));
    } else {
      const channels = new Set(items.map((item) => item.channel)).size;
      add(items.length + " effects selected on " + channels + " channel(s)", true);
    }
    const editable = items.every((item) => EDITABLE_TYPES.includes(item.effect.type));
    const form = document.createElement("div");
    form.className = "edit-form";
    const current = intensityOf(first);
    let type = null;
    let fade = null;
    if (editable) {
      type = document.createElement("select");
      type.id = "editType";
      for (const name of EDITABLE_TYPES) {
        const option = document.createElement("option");
        option.value = name;
        option.textContent = name.charAt(0) + name.slice(1).toLowerCase();
        type.appendChild(option);
      }
      type.value = first.type;
      form.appendChild(field("Effect", type));
      fade = document.createElement("input");
      fade.type = "checkbox";
      fade.id = "editFade";
      fade.checked = current.fade;
      form.appendChild(field("Fade", fade));
      form.appendChild(field("Level %", numberInput("editIntensity", current.level, 0, 100, 1)));
      form.appendChild(field("From %", numberInput("editStartIntensity", current.start, 0, 100, 1)));
      form.appendChild(field("To %", numberInput("editEndIntensity", current.end, 0, 100, 1)));
      const sync = () => {
        const fading = type.value === "INTENSITY" && fade.checked;
        fade.disabled = type.value !== "INTENSITY";
        $("editIntensity").parentElement.classList.toggle("hidden", fading);
        $("editStartIntensity").parentElement.classList.toggle("hidden", !fading);
        $("editEndIntensity").parentElement.classList.toggle("hidden", !fading);
      };
      type.addEventListener("change", sync);
      fade.addEventListener("change", sync);
      inspector.appendChild(form);
      sync();
    } else {
      add("This effect type's own settings are kept as they are; its timing can still change.");
      inspector.appendChild(form);
    }
    if (items.length === 1) {
      form.appendChild(field("Start s", numberInput("editStart", (first.start / 100).toFixed(2), 0,
        null, 0.01)));
      form.appendChild(field("End s", numberInput("editEnd", (first.end / 100).toFixed(2), 0,
        null, 0.01)));
    }
    const apply = document.createElement("button");
    apply.type = "button";
    apply.id = "editApply";
    apply.className = "tool-button primary";
    apply.textContent = "Apply";
    apply.addEventListener("click", () => {
      const values = {};
      const percent = (id) => {
        const raw = $(id).value.trim();
        const value = Number(raw);
        if (!raw || !Number.isInteger(value) || value < 0 || value > 100) {
          throw new Error("intensities are whole numbers from 0 to 100");
        }
        return value;
      };
      try {
        if (editable) {
          values.type = type.value;
          const fading = type.value === "INTENSITY" && fade.checked;
          values.intensity = fading
            ? { fade: true, start: percent("editStartIntensity"), end: percent("editEndIntensity") }
            : { fade: false, level: percent("editIntensity") };
        }
        if (items.length === 1) {
          const startText = $("editStart").value.trim();
          const endText = $("editEnd").value.trim();
          values.start = Math.round(Number(startText) * 100);
          values.end = Math.round(Number(endText) * 100);
          if (!startText || !endText || !Number.isFinite(values.start) || !Number.isFinite(values.end)) {
            throw new Error("times must be numbers of seconds");
          }
        }
      } catch (error) {
        setBanner("Not changed: " + error.message + ".", "warn");
        return;
      }
      setProperties(items, values);
    });
    form.appendChild(apply);
  }

  // --- Export ----------------------------------------------------------------

  function rewriteChannelNode(channel) {
    const node = channel.node;
    const doc = node.ownerDocument;
    const before = node.previousSibling;
    const indent = before && before.nodeType === 3 ? before.nodeValue.split("\n").pop() : "";
    const inner = indent + "  ";
    const others = Array.from(node.children).filter((child) => child.localName !== "effect");
    node.replaceChildren();
    const children = channel.effects.map((effect) => {
      const element = doc.createElementNS(null, "effect");
      for (const key of Object.keys(effect.attributes)) {
        const value = key === "startCentisecond" ? String(effect.start)
          : key === "endCentisecond" ? String(effect.end) : effect.attributes[key];
        element.setAttribute(key, value);
      }
      return element;
    }).concat(others);
    for (const child of children) {
      node.appendChild(doc.createTextNode("\n" + inner));
      node.appendChild(child);
    }
    if (children.length) node.appendChild(doc.createTextNode("\n" + indent));
  }

  function serializeSequence() {
    const sequence = state.sequence;
    for (const prop of sequence.props) {
      for (const channel of prop.channels) if (channel.edited) rewriteChannelNode(channel);
    }
    const source = sequence.source;
    let text = new XMLSerializer().serializeToString(sequence.doc)
      .replace(/^<\?xml[^?]*\?>\s*/, "");
    if (source.spacedEmpty) text = text.replace(/([^\s/])\/>/g, "$1 />");
    text = source.declaration + "\n" + text + source.trailing;
    if (source.crlf) text = text.replace(/\r?\n/g, "\r\n");
    return (source.bom ? "﻿" : "") + text;
  }

  async function exportEdited() {
    const sequence = state.sequence;
    if (!sequence || state.exportPending) return;
    const revision = state.editRevision;
    const requestId = ++state.exportRequestId;
    const text = serializeSequence();
    if (text.length > MAX_XML_BYTES) {
      setBanner("The edited sequence exceeds the 50 MiB limit.", "error");
      return;
    }
    state.exportPending = true;
    updateEditControls();
    let result;
    try {
      result = await callEngine("/api/export", JSON.stringify({ original: sequence.source.originalXml,
        edited: text }), "application/json");
    } catch (error) {
      if (requestId === state.exportRequestId && state.sequence === sequence) {
        setBanner("Not saved: " + problemText(error), "error");
      } else {
        logProblem("An export of a previous workspace could not be completed: " + problemText(error),
          "export");
      }
      return;
    } finally {
      if (requestId === state.exportRequestId) {
        state.exportPending = false;
        updateEditControls();
      }
    }
    // A show generated here is saved under its own name; an opened file gets "(edited)".
    const name = sequence.generated ? sequence.filename
      : sequence.filename.replace(/\.(loredit|xml)$/i, "") + " (edited).loredit";
    const url = URL.createObjectURL(new Blob([text], { type: "application/xml" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    if (state.sequence === sequence && state.editRevision === revision) {
      for (const prop of sequence.props) {
        for (const channel of prop.channels) state.baselineEffects.set(channel, channel.effects);
      }
      state.dirty = false;
      state.exported = true;
      updateEditControls();
      setBanner("Checked and saved " + name + " with " + result.effects.toLocaleString() +
        " effects. Your original file is unchanged.", "good");
    } else {
      setBanner("Saved " + name + " as it was when you clicked Save. The workspace changed while it was being checked; current edits remain unsaved.", "warn");
    }
  }

  function setupEditing() {
    const canvas = $("tracksCanvas");
    canvas.addEventListener("pointerdown", handleTrackPointerDown);
    canvas.addEventListener("pointermove", handleTrackPointerMove);
    canvas.addEventListener("pointerup", handleTrackPointerUp);
    canvas.addEventListener("pointercancel", () => {
      const cancelled = Boolean(state.drag);
      state.drag = null;
      if (cancelled) setBanner("Drag cancelled; no sequence changes were made.", "warn");
      if (state.sequence) drawTracks(Number(canvas.width), state.pxPerSecond);
    });
    canvas.addEventListener("dblclick", handleTrackDoubleClick);
    document.addEventListener("keydown", handleEditKey);
    $("undoButton").addEventListener("click", undoEdit);
    $("redoButton").addEventListener("click", redoEdit);
    $("deleteButton").addEventListener("click", deleteSelection);
    $("duplicateButton").addEventListener("click", duplicateSelection);
    $("exportButton").addEventListener("click", exportEdited);
    $("saveReviewButton").addEventListener("click", saveReview);
    const markers = $("markersCanvas");
    markers.addEventListener("pointerdown", handleMarkerPointerDown);
    markers.addEventListener("pointermove", handleMarkerPointerMove);
    markers.addEventListener("pointerup", handleMarkerPointerUp);
    markers.addEventListener("pointercancel", () => {
      const cancelled = Boolean(state.reviewDrag);
      state.reviewDrag = null;
      if (cancelled) setBanner("Marker drag cancelled; no music-review changes were made.", "warn");
      if (state.sequence) drawMarkers(Number(markers.width), state.pxPerSecond);
    });
    markers.addEventListener("dblclick", handleMarkerDoubleClick);
    window.addEventListener("beforeunload", (event) => {
      if (state.dirty || state.reviewDirty) event.preventDefault();
    });
  }

  // ---------------------------------------------------------------------------
  // Music review: correct the musical reference lanes. Beats, bars, crashes, high
  // hits, sections and lyric lines can be moved, added, deleted and confirmed. A
  // marker the user placed or confirmed is "confirmed"; markers fitted between two
  // confirmed bars are "fitted"; everything else stays "auto". Changes share the
  // effect editor's undo history and are saved as a music review file that the
  // generator accepts in place of an analysis.

  const REVIEW_LANES = {
    beats: { key: "beats", name: "Beat" },
    downbeats: { key: "downbeats", name: "Bar" },
    crashes: { key: "crashes", name: "Crash" },
    hits: { key: "high_hits", name: "High hit" },
    sections: { key: "section_candidates", name: "Section" }
  };
  const SECTION_LABELS = ["Intro", "Verse", "Pre-chorus", "Chorus", "Bridge", "Instrumental",
    "Breakdown", "Solo", "Outro", "Finale"];
  const MARKER_PIXELS = 6;
  const REVIEW_SCHEMA = "music-review-1.0";

  function reviewLane(lane) {
    if (!lane) return null;
    if (lane.kind === "lyrics") return state.lyrics ? { owner: state.lyrics, key: "lines", name: "Lyric line" } : null;
    const spec = REVIEW_LANES[lane.kind];
    const analysis = state.analysis && state.analysis.analysis;
    if (!spec || !analysis || !Array.isArray(analysis[spec.key])) return null;
    return { owner: analysis, key: spec.key, name: spec.name };
  }

  function eventTime(event) {
    return Number(event.time != null ? event.time : event.start);
  }

  function statusOf(event) {
    if (event.status) return event.status;
    if (event.text != null) return event.verified ? "confirmed" : "auto";
    return "auto";
  }

  function laneByKind(kind) {
    return state.lanes.find((lane) => lane.kind === kind) || null;
  }

  function reviewSelect(selection) {
    state.reviewSelection = selection;
    if (selection) setSelection([]);
    renderReviewInspector();
    drawMarkers(Number($("markersCanvas").width), state.pxPerSecond);
  }

  function musicChange(target, after) {
    return { owner: target.owner, key: target.key, before: target.owner[target.key], after };
  }

  function applyMusic(label, changes, select) {
    try {
      for (const change of changes) {
        if (state.lyrics && change.owner === state.lyrics && change.key === "lines") {
          checkLyrics({ schema_version: "lyrics-1.0", source: state.lyrics.source, lines: change.after });
          continue;
        }
        const duration = Number(state.analysis && state.analysis.audio &&
          state.analysis.audio.duration_seconds);
        if (change.owner === (state.analysis && state.analysis.analysis) &&
            Object.values(REVIEW_LANES).some((spec) => spec.key === change.key) &&
            (!Number.isFinite(duration) || change.after.some((event) =>
              !Number.isFinite(eventTime(event)) || eventTime(event) < 0 ||
              eventTime(event) > duration + 1))) {
          throw new Error("a marker must be within the analyzed song");
        }
      }
    } catch (error) {
      setBanner("Not changed: " + error.message + ".", "warn");
      return false;
    }
    const command = { label, music: changes };
    performMusic(command, "after");
    state.undo.push(command);
    if (state.undo.length > MAX_UNDO) state.undo.shift();
    state.redo = [];
    afterMusicEdit(select);
    setBanner(label + ". Undo with Ctrl+Z.", "good");
  }

  function performMusic(command, side) {
    for (const change of command.music) change.owner[change.key] = change[side];
  }

  function captureReviewBaseline() {
    const analysis = state.analysis && state.analysis.analysis;
    const lanes = {};
    for (const spec of Object.values(REVIEW_LANES)) {
      lanes[spec.key] = analysis ? analysis[spec.key] : null;
    }
    state.reviewBaseline = { analysis, lanes, lyrics: state.lyrics,
      lyricLines: state.lyrics ? state.lyrics.lines : null };
  }

  function reviewHasChanges() {
    const baseline = state.reviewBaseline;
    if (!baseline) return Boolean(state.analysis || state.lyrics);
    const analysis = state.analysis && state.analysis.analysis;
    if (analysis !== baseline.analysis) return true;
    for (const spec of Object.values(REVIEW_LANES)) {
      if (analysis && analysis[spec.key] !== baseline.lanes[spec.key]) return true;
    }
    return state.lyrics !== baseline.lyrics ||
      Boolean(state.lyrics && state.lyrics.lines !== baseline.lyricLines);
  }

  function afterMusicEdit(select) {
    state.reviewDirty = reviewHasChanges();
    state.syncCheck = null;
    refreshTimeline();
    updateEditControls();
    if (select && select.event) {
      const lane = laneByKind(select.kind);
      reviewSelect(lane ? { kind: select.kind, event: select.event } : null);
    } else {
      reviewSelect(null);
    }
  }

  function sortedByTime(events) {
    return events.slice().sort((a, b) => eventTime(a) - eventTime(b));
  }

  function round3(value) {
    return Math.round(value * 1000) / 1000;
  }

  function movedEvent(event, seconds) {
    if (event.text != null) {
      const delta = seconds - Number(event.start);
      return Object.assign({}, event, {
        start: round3(seconds), end: round3(Number(event.end) + delta),
        words: (event.words || []).map((word) => Object.assign({}, word, {
          start: round3(Number(word.start) + delta), end: round3(Number(word.end) + delta)
        }))
      });
    }
    return Object.assign({}, event, { time: round3(seconds), status: "confirmed" });
  }

  function newMarker(kind, seconds) {
    if (kind === "sections") {
      return { time: round3(seconds), kind: "structural_change_candidate", relative_change: 0,
        confidence: 1, label: null, method: "placed in music review", status: "confirmed" };
    }
    return { time: round3(seconds), confidence: 1, method: "placed in music review",
      status: "confirmed" };
  }

  function replaceEvent(target, event, replacement) {
    const list = target.owner[target.key].slice();
    const index = list.indexOf(event);
    if (index < 0) return null;
    if (replacement) list[index] = replacement;
    else list.splice(index, 1);
    return sortedByTime(list);
  }

  function markerHit(event) {
    const canvas = $("markersCanvas");
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const lane = state.lanes[Math.floor((event.clientY - rect.top) / MARKER_HEIGHT)];
    const seconds = clampReviewSeconds(Math.max(0, x / state.pxPerSecond));
    const hit = { lane, x, seconds, target: reviewLane(lane), event: null, edge: null };
    if (!hit.target) return hit;
    const pps = state.pxPerSecond;
    if (lane.kind === "lyrics") {
      for (const line of hit.target.owner.lines) {
        const x1 = Number(line.start) * pps;
        const x2 = Number(line.end) * pps;
        if (x < x1 - 4 || x > x2 + 4) continue;
        if (x2 - x1 > 14 && Math.abs(x - x2) <= 4) return Object.assign(hit, { event: line, edge: "end" });
        if (x2 - x1 > 14 && Math.abs(x - x1) <= 4) return Object.assign(hit, { event: line, edge: "start" });
        if (x >= x1 && x < x2) return Object.assign(hit, { event: line });
      }
      return hit;
    }
    let best = null;
    for (const item of hit.target.owner[hit.target.key]) {
      const distance = Math.abs(eventTime(item) * pps - x);
      if (distance <= MARKER_PIXELS && (best == null || distance < best.distance)) {
        best = { item, distance };
      }
    }
    if (best) hit.event = best.item;
    return hit;
  }

  function reviewCandidates(ownSeconds) {
    const own = Math.round(ownSeconds * 100);
    return snapCandidates().filter((cs) => cs !== own);
  }

  function handleMarkerPointerDown(event) {
    if (!state.sequence || event.button !== 0) return;
    const hit = markerHit(event);
    if (!hit.event) {
      state.reviewDrag = null;
      if (state.reviewSelection) reviewSelect(null);
      handleMarkerClick(event);
      return;
    }
    const seconds = eventTime(hit.event);
    seekAudio(hit.edge === "end" ? Number(hit.event.end) : seconds);
    reviewSelect({ kind: hit.lane.kind, event: hit.event });
    state.reviewDrag = { hit, startX: event.clientX, moved: false, preview: null,
      candidates: reviewCandidates(hit.edge === "end" ? Number(hit.event.end) : seconds) };
    $("markersCanvas").setPointerCapture(event.pointerId);
  }

  function handleMarkerPointerMove(event) {
    const drag = state.reviewDrag;
    const canvas = $("markersCanvas");
    if (!drag) {
      if (!state.sequence) return;
      const hit = markerHit(event);
      canvas.style.cursor = hit.edge ? "ew-resize" : hit.event ? "grab" : hit.target ? "copy" : "pointer";
      return;
    }
    if (!drag.moved && Math.abs(event.clientX - drag.startX) < DRAG_THRESHOLD) return;
    drag.moved = true;
    const rect = canvas.getBoundingClientRect();
    const raw = clampReviewSeconds(Math.max(0, (event.clientX - rect.left) / state.pxPerSecond));
    const { hit } = drag;
    let cs = snap(Math.round(raw * 100), drag.candidates, event.altKey);
    cs = Math.round(clampReviewSeconds(cs / 100) * 100);
    if (hit.edge) {
      cs = snap(Math.round(raw * 100), drag.candidates, event.altKey);
    } else if (hit.lane.kind === "lyrics") {
      const offset = drag.hit.seconds - Number(hit.event.start);
      cs = snap(Math.round((raw - offset) * 100), drag.candidates, event.altKey);
      cs = Math.round(clampReviewSeconds(cs / 100) * 100);
    }
    drag.preview = clampReviewSeconds(cs / 100);
    setBanner((hit.edge ? "Line " + hit.edge + " " : hit.target.name + " ") + "→ " +
      formatCentiseconds(cs) + (event.altKey ? " (snapping off)" : ""), "");
    drawMarkers(Number(canvas.width), state.pxPerSecond);
  }

  function handleMarkerPointerUp() {
    const drag = state.reviewDrag;
    state.reviewDrag = null;
    if (!drag || !drag.moved || drag.preview == null) {
      if (drag) drawMarkers(Number($("markersCanvas").width), state.pxPerSecond);
      return;
    }
    const { hit } = drag;
    let replacement;
    if (hit.edge) {
      const duration = currentMusicDuration();
      const originalStart = Number(hit.event.start);
      const originalEnd = Number(hit.event.end);
      const start = hit.edge === "start"
        ? Math.min(drag.preview, originalEnd - 0.05) : originalStart;
      const end = hit.edge === "end"
        ? Math.min(drag.preview, duration == null ? drag.preview : duration) : originalEnd;
      if (end - start < 0.05) {
        setBanner("Not changed: a lyric line needs some length.", "warn");
        drawMarkers(Number($("markersCanvas").width), state.pxPerSecond);
        return;
      }
      const words = (hit.event.words || []).filter((word) =>
        Number(word.end) > start && Number(word.start) < end).map((word) => Object.assign({}, word, {
        start: round3(Math.max(start, Number(word.start))),
        end: round3(Math.min(end, Number(word.end)))
      })).filter((word) => word.end > word.start);
      replacement = Object.assign({}, hit.event, { start: round3(start), end: round3(end), words });
    } else if (hit.lane.kind === "lyrics") {
      const duration = currentMusicDuration();
      const length = Number(hit.event.end) - Number(hit.event.start);
      const latestStart = duration == null ? 1800 - length : Math.max(0, duration - length);
      replacement = movedEvent(hit.event, Math.min(drag.preview, latestStart));
    } else {
      replacement = movedEvent(hit.event, drag.preview);
    }
    const after = replaceEvent(hit.target, hit.event, replacement);
    if (!after) {
      setBanner("Not changed: the selected marker is no longer available.", "warn");
      return;
    }
    applyMusic((hit.edge ? "Trimmed a lyric line" : "Moved a " + hit.target.name.toLowerCase()) +
      " to " + formatCentiseconds(drag.preview * 100), [musicChange(hit.target, after)],
    { kind: hit.lane.kind, event: replacement });
  }

  function handleMarkerDoubleClick(event) {
    if (!state.sequence) return;
    const hit = markerHit(event);
    if (!hit.target || hit.event) return;
    const seconds = clampReviewSeconds(
      snap(Math.round(hit.seconds * 100), snapCandidates(), event.altKey) / 100);
    let created;
    if (hit.lane.kind === "lyrics") {
      const duration = currentMusicDuration();
      const end = Math.min(duration == null ? 1800 : duration, seconds + 2);
      if (end - seconds < 0.05) {
        setBanner("Not changed: there is not enough song left for a lyric line.", "warn");
        return;
      }
      created = { start: round3(seconds), end: round3(end), text: "(new line)",
        verified: false, words: [] };
    } else {
      created = newMarker(hit.lane.kind, seconds);
    }
    const after = sortedByTime(hit.target.owner[hit.target.key].concat([created]));
    applyMusic("Added a " + hit.target.name.toLowerCase() + " at " +
      formatCentiseconds(seconds * 100), [musicChange(hit.target, after)],
    { kind: hit.lane.kind, event: created });
  }

  function deleteReviewSelection() {
    const selection = state.reviewSelection;
    const target = selection && reviewLane(laneByKind(selection.kind));
    if (!target) return false;
    const after = replaceEvent(target, selection.event, null);
    if (!after) return false;
    applyMusic("Deleted a " + target.name.toLowerCase(), [musicChange(target, after)], null);
    return true;
  }

  function confirmReviewSelection() {
    const selection = state.reviewSelection;
    const target = selection && reviewLane(laneByKind(selection.kind));
    if (!target || statusOf(selection.event) === "confirmed") return false;
    const replacement = selection.event.text != null
      ? Object.assign({}, selection.event, { verified: true,
        words: (selection.event.words || []).map((word) => Object.assign({}, word, { verified: true })) })
      : Object.assign({}, selection.event, { status: "confirmed" });
    applyMusic("Confirmed a " + target.name.toLowerCase(),
      [musicChange(target, replaceEvent(target, selection.event, replacement))],
      { kind: selection.kind, event: replacement });
    return true;
  }

  function editSelected(values) {
    const selection = state.reviewSelection;
    const target = selection && reviewLane(laneByKind(selection.kind));
    if (!target) return;
    const event = selection.event;
    let replacement;
    if (event.text != null) {
      const text = values.text.trim().replace(/\s+/g, " ");
      if (!text) {
        setBanner("Not changed: a lyric line needs words.", "warn");
        return;
      }
      const duration = currentMusicDuration();
      if (!(values.end - values.start >= 0.05) || values.start < 0 ||
          (duration != null && values.end > duration)) {
        setBanner("Not changed: the line must have a positive length and stay within the selected song.", "warn");
        return;
      }
      const delta = values.start - Number(event.start);
      let words = (event.words || []).map((word) => Object.assign({}, word, {
        start: round3(Number(word.start) + delta), end: round3(Number(word.end) + delta)
      }));
      const typed = text.split(" ");
      if (text !== event.text) {
        // Typed corrections keep the recognizer's word timings when the word count
        // still matches; otherwise the line keeps only its own start and end.
        words = typed.length === words.length
          ? words.map((word, index) => Object.assign({}, word, { text: typed[index], verified: true }))
          : [];
      }
      words = words.filter((word) => Number(word.end) > values.start &&
        Number(word.start) < values.end).map((word) => Object.assign({}, word, {
        start: round3(Math.max(values.start, Number(word.start))),
        end: round3(Math.min(values.end, Number(word.end)))
      })).filter((word) => word.end > word.start);
      replacement = Object.assign({}, event, { text, start: round3(values.start),
        end: round3(values.end), words, verified: true });
    } else {
      const duration = currentMusicDuration();
      if (values.time < 0 || (duration != null && values.time > duration)) {
        setBanner("Not changed: the marker must stay within the selected song.", "warn");
        return;
      }
      replacement = Object.assign({}, event, { time: round3(values.time), status: "confirmed" });
      if (selection.kind === "sections") replacement.label = values.label || null;
    }
    applyMusic("Changed a " + target.name.toLowerCase(),
      [musicChange(target, replaceEvent(target, event, replacement))],
      { kind: selection.kind, event: replacement });
  }

  function medianBarSeconds() {
    const analysis = state.analysis && state.analysis.analysis;
    const times = sortedTimes(analysis ? analysis.downbeats : []);
    const gaps = [];
    for (let index = 1; index < times.length; index++) gaps.push(times[index] - times[index - 1]);
    gaps.sort((a, b) => a - b);
    return gaps.length ? gaps[Math.floor(gaps.length / 2)] : null;
  }

  function nextConfirmedBar(time) {
    const analysis = state.analysis.analysis;
    return sortedByTime(analysis.downbeats).find((event) =>
      statusOf(event) === "confirmed" && eventTime(event) > time + 0.05) || null;
  }

  // Tempo map: spread the bars and beats evenly between two confirmed bars. This
  // handles rubato and tempo changes one stretch at a time, anchored on the bars
  // the user placed by ear.
  function fitBetweenBars(bar, bars) {
    const analysis = state.analysis.analysis;
    const next = nextConfirmedBar(eventTime(bar));
    if (!next || !(bars >= 1 && bars <= 64 && Number.isInteger(bars))) return;
    const meter = Number($("meterSelect").value) || 4;
    const start = eventTime(bar);
    const end = eventTime(next);
    const method = "fitted between confirmed bars (" + bars + " bars of " + meter + ")";
    const step = (end - start) / (bars * meter);
    const beats = analysis.beats.filter((event) =>
      eventTime(event) < start - 0.05 || eventTime(event) > end + 0.05);
    for (let index = 0; index <= bars * meter; index++) {
      const fixed = index === 0 || index === bars * meter;
      beats.push({ time: round3(start + index * step), confidence: 1, method,
        status: fixed ? "confirmed" : "fitted" });
    }
    const downbeats = analysis.downbeats.filter((event) =>
      eventTime(event) <= start + 0.05 || eventTime(event) >= end - 0.05);
    for (let index = 1; index < bars; index++) {
      downbeats.push({ time: round3(start + index * step * meter), confidence: 1, method,
        status: "fitted" });
    }
    const target = (key) => ({ owner: analysis, key });
    applyMusic("Fitted " + bars + " bar(s) of " + meter + " between " + formatCentiseconds(start * 100) +
      " and " + formatCentiseconds(end * 100) + ": " + (60 / step).toFixed(1) + " BPM",
    [musicChange(target("beats"), sortedByTime(beats)),
      musicChange(target("downbeats"), sortedByTime(downbeats))], { kind: "downbeats", event: bar });
  }

  function reviewButton(id, text, handler, primary) {
    const button = document.createElement("button");
    button.type = "button";
    button.id = id;
    button.className = "tool-button" + (primary ? " primary" : "") + " inspector-action";
    button.textContent = text;
    button.addEventListener("click", handler);
    return button;
  }

  function renderReviewInspector() {
    const selection = state.reviewSelection;
    if (!selection) return;
    const lane = laneByKind(selection.kind);
    const target = reviewLane(lane);
    if (!target) return;
    const event = selection.event;
    const seconds = eventTime(event);
    inspectMoment(seconds, lane);
    const inspector = $("inspectorContent");
    const status = statusOf(event);
    const note = document.createElement("div");
    note.className = "inspector-primary";
    note.textContent = target.name + " · " + (status === "confirmed" ? "confirmed by you"
      : status === "fitted" ? "fitted between confirmed bars" : "automatic estimate" +
        (event.method ? " (" + event.method + ")" : ""));
    inspector.insertBefore(note, inspector.children[1] || null);
    const form = document.createElement("div");
    form.className = "edit-form";
    if (event.text != null) {
      const text = document.createElement("input");
      text.type = "text";
      text.id = "reviewText";
      text.className = "review-text";
      text.value = event.text;
      form.appendChild(field("Words", text));
      form.appendChild(field("Start s", numberInput("reviewStart", Number(event.start).toFixed(2), 0, null, 0.01)));
      form.appendChild(field("End s", numberInput("reviewEnd", Number(event.end).toFixed(2), 0, null, 0.01)));
    } else {
      form.appendChild(field("Time s", numberInput("reviewTime", seconds.toFixed(3), 0, null, 0.001)));
      if (selection.kind === "sections") {
        const label = document.createElement("select");
        label.id = "reviewLabel";
        for (const name of [""].concat(SECTION_LABELS)) {
          const option = document.createElement("option");
          option.value = name;
          option.textContent = name || "(unlabeled)";
          label.appendChild(option);
        }
        label.value = event.label || "";
        form.appendChild(field("Part", label));
      }
    }
    form.appendChild(reviewButton("reviewApply", "Apply", () => {
      if (event.text != null) {
        const startText = $("reviewStart").value.trim();
        const endText = $("reviewEnd").value.trim();
        if (!startText || !endText) {
          setBanner("Not changed: lyric start and end must both be numbers of seconds.", "warn");
          return;
        }
        editSelected({ text: $("reviewText").value, start: Number(startText), end: Number(endText) });
      } else {
        const timeText = $("reviewTime").value.trim();
        const time = Number(timeText);
        if (!timeText || !Number.isFinite(time) || time < 0) {
          setBanner("Not changed: the time must be a number of seconds.", "warn");
          return;
        }
        editSelected({ time, label: $("reviewLabel") ? $("reviewLabel").value : null });
      }
    }, true));
    if (status !== "confirmed") {
      form.appendChild(reviewButton("reviewConfirm", event.text != null ? "Confirm words" : "Confirm",
        confirmReviewSelection));
    }
    form.appendChild(reviewButton("reviewDelete", "Delete", deleteReviewSelection));
    inspector.appendChild(form);
    if (selection.kind === "downbeats" && status === "confirmed") {
      const next = nextConfirmedBar(seconds);
      const fit = document.createElement("div");
      fit.className = "edit-form";
      if (next) {
        const gap = eventTime(next) - seconds;
        const bar = medianBarSeconds();
        const bars = numberInput("fitBars", Math.max(1, Math.round(bar ? gap / bar : 1)), 1, 64, 1);
        fit.appendChild(field("Bars to " + formatCentiseconds(eventTime(next) * 100), bars));
        fit.appendChild(reviewButton("fitBarsButton", "Fit bars and beats evenly", () => {
          const raw = $("fitBars").value.trim();
          const count = Number(raw);
          if (!raw || !Number.isInteger(count) || count < 1 || count > 64) {
            setBanner("Not changed: enter a whole number of bars from 1 to 64.", "warn");
            return;
          }
          fitBetweenBars(event, count);
        }));
      } else {
        const hint = document.createElement("div");
        hint.textContent = "Confirm a later bar to fit the bars and beats between them.";
        fit.appendChild(hint);
      }
      inspector.appendChild(fit);
    }
  }

  // --- Saving and loading a review ----------------------------------------------

  function reviewCounts() {
    const counts = { confirmed: 0, fitted: 0, auto: 0, lyric_lines_confirmed: 0, lyric_lines: 0 };
    const analysis = state.analysis && state.analysis.analysis;
    for (const spec of Object.values(REVIEW_LANES)) {
      for (const event of (analysis && analysis[spec.key]) || []) counts[statusOf(event)] += 1;
    }
    for (const line of state.lyrics ? state.lyrics.lines : []) {
      counts.lyric_lines += 1;
      if (line.verified) counts.lyric_lines_confirmed += 1;
    }
    return counts;
  }

  function saveReview() {
    if (!state.analysis) {
      setBanner("Load or run an audio analysis first; the review corrects it.", "warn");
      return;
    }
    const base = (state.sequence ? state.sequence.filename : "song").replace(/\.(loredit|xml)$/i, "");
    const document_ = {
      schema_version: REVIEW_SCHEMA,
      created_by: "lor-sequence-ui",
      sequence_file: state.sequence ? state.sequence.filename : null,
      meter: Number($("meterSelect").value) || 4,
      counts: reviewCounts(),
      analysis: state.analysis,
      lyrics: state.lyrics
    };
    const url = URL.createObjectURL(new Blob([JSON.stringify(document_, null, 2) + "\n"],
      { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = base + ".review.json";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    captureReviewBaseline();
    state.reviewDirty = false;
    state.reviewSaved = true;
    updateEditControls();
    setBanner("Saved " + base + ".review.json. Open it again with Load analysis, or generate from it " +
      "with --analysis.", "good");
  }

  // ---------------------------------------------------------------------------
  // Build a new show: the display preview, the song, optional requirements, then
  // generate. Each step runs in the local engine (see show_builder.py); the result
  // opens in the workspace to review, and is saved as a new file.

  const SECTION_NAMES = ["intro", "verse", "pre-chorus", "chorus", "bridge", "instrumental",
    "breakdown", "solo", "outro", "finale"];
  const REQUIREMENT_KINDS = {
    keep_on: "Keep on all song",
    never_use: "Never use",
    quiet_during: "Keep dark during",
    max_intensity: "Limit brightness to"
  };

  const show = { token: null, summary: null, audioFile: null, analysis: null, raw: [],
    result: null, resultConfig: null, audioRequestId: 0, audioPending: false, analysisMeter: null,
    requirementsPending: false, requirementsRequestId: 0, displayRequestId: 0,
    displayPending: false, testPending: false, batchRunning: false, batchToken: null,
    batchConfig: null, batchReady: false, batchZipPending: false, generationPending: false };

  function showMessage(id, text, kind) {
    const element = $(id);
    element.textContent = text;
    element.className = "step-status" + (kind ? " " + kind : "");
    if (kind === "error") remember("showed in " + id + ": " + text);
  }

  async function postShow(path, body, type) {
    return callEngine(path, body, type);
  }


  function openNewShow() {
    $("welcome").classList.add("hidden");
    $("editor").classList.add("hidden");
    $("newShow").classList.remove("hidden");
  }

  function closeNewShow() {
    $("newShow").classList.add("hidden");
    if (state.sequence) $("editor").classList.remove("hidden");
    else $("welcome").classList.remove("hidden");
  }

  function bytesFromBase64(text) {
    const raw = atob(text);
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    return bytes;
  }

  function download(bytes, name, type) {
    const url = URL.createObjectURL(new Blob([bytes], { type }));
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  }

  async function makeDisplayTest() {
    if (!show.token || show.testPending || show.batchRunning || show.generationPending ||
        show.batchZipPending || show.displayPending || show.audioPending || show.requirementsPending) return;
    const token = show.token;
    show.test = null;
    $("watchTest").disabled = true;
    $("saveTest").disabled = true;
    show.testPending = true;
    setShowConfigurationLocked(true);
    setStepEnabled();
    showMessage("testStatus", "Making the display test…");
    try {
      const test = await withProgress("testStatus", "Starting", (key) =>
        postShow("/api/show/test?token=" + encodeURIComponent(token) + "&progress=" + key,
          "{}", "application/json"));
      if (show.token !== token) return;
      show.test = test;
      showMessage("testStatus", "Ready: " + test.schedule.length + " steps in 10 seconds. Save the " +
        "files, copy the sound into S6's audio folder, and play the sequence in S6; the text " +
        "file says what should light when. Watch the test to see it here first.", "good");
      $("watchTest").disabled = false;
      $("saveTest").disabled = false;
    } catch (error) {
      if (show.token === token) showMessage("testStatus", error.message || String(error), "error");
    } finally {
      show.testPending = false;
      setShowConfigurationLocked(false);
      setStepEnabled();
    }
  }

  function saveDisplayTest() {
    if (show.test) download(bytesFromBase64(show.test.zip), show.test.zip_name, "application/zip");
  }

  function confirmSequenceReplacement() {
    if (state.dirty && !window.confirm("Discard the unexported edits to " +
        state.sequence.filename + "?")) return false;
    if (state.reviewDirty && !window.confirm("Replace the unsaved music review?")) return false;
    return true;
  }

  async function watchDisplayTest() {
    const test = show.test;
    if (!test || generatedActionsBlocked() || !confirmSequenceReplacement()) return;
    openSequenceText(test.sequence, test.file_name, false);
    state.sequence.generated = true;
    updateEditControls();
    toggleYard(true);
    setBanner("Display test: press play and watch each kind of prop, then the sweep from left " +
      "to right, then everything on.", "good");
    const sound = new File([bytesFromBase64(test.sound)], test.sound_name, { type: "audio/wav" });
    await loadAudio(sound, null, true);
  }

  function currentBatchConfig() {
    return JSON.stringify({
      token: show.token,
      meter: $("meterSelect").value,
      style: chosenStyle(),
      requirements: show.raw || []
    });
  }

  function currentShowConfig() {
    return JSON.stringify({
      token: show.token,
      song: show.songName || "",
      meter: $("meterSelect").value,
      style: chosenStyle(),
      requirements: show.raw || [],
      musicFilename: $("musicFilename").value,
      singing: $("singFaces").checked && !$("singFaces").closest("label").classList.contains("hidden")
    });
  }

  function generatedActionsBlocked() {
    return state.audioDecodePending || show.audioPending || show.requirementsPending ||
      show.displayPending || show.generationPending || show.batchRunning ||
      show.batchZipPending || show.testPending;
  }

  function updateGeneratedControls() {
    const ready = !generatedActionsBlocked() && resultIsCurrent();
    for (const id of ["openGenerated", "saveGenerated", "pictureGenerated", "reportGenerated"]) {
      $(id).disabled = !ready;
    }
  }

  function invalidateGeneratedResult() {
    show.result = null;
    show.resultConfig = null;
    updateGeneratedControls();
    $("showNotes").replaceChildren();
  }

  function setShowConfigurationLocked(locked) {
    for (const id of ["showDisplayFile", "showSongFile", "requirementKind", "requirementProps",
      "requirementSections", "requirementMax", "addRequirement", "translateRequirements",
      "plainRequirements", "musicFilename", "singFaces", "meterSelect", "styleChoices",
      "closeNewShow"]) {
      const element = $(id);
      if (!element) continue;
      if ("disabled" in element) element.disabled = locked;
      element.querySelectorAll("input, select, textarea, button").forEach((child) => {
        child.disabled = locked;
      });
    }
    $("requirementList").querySelectorAll("button").forEach((button) => { button.disabled = locked; });
  }

  function setRequirementControlsLocked(locked) {
    for (const id of ["requirementKind", "requirementProps", "requirementSections",
      "requirementMax", "addRequirement", "translateRequirements", "plainRequirements"]) {
      const element = $(id);
      if (!element) continue;
      if ("disabled" in element) element.disabled = locked;
      element.querySelectorAll("input, select, textarea, button").forEach((child) => {
        child.disabled = locked;
      });
    }
    $("requirementList").querySelectorAll("button").forEach((button) => { button.disabled = locked; });
  }

  function setStepEnabled() {
    $("watchTest").disabled = !show.test || generatedActionsBlocked();
    $("saveTest").disabled = !show.test;
    $("makeTest").disabled = !show.token || show.batchRunning || show.generationPending ||
      show.batchZipPending || show.displayPending || show.testPending || show.audioPending || show.requirementsPending;
    $("showSongFile").disabled = !show.token || show.batchRunning || show.generationPending ||
      show.batchZipPending || show.displayPending || show.testPending || show.audioPending || show.requirementsPending;
    $("meterSelect").disabled = state.audioDecodePending || show.batchRunning || show.generationPending ||
      show.batchZipPending || show.displayPending || show.testPending || show.audioPending ||
      show.requirementsPending;
    $("showSongLabel").classList.toggle("disabled", !show.token);
    $("addRequirement").disabled = !show.token || show.testPending || show.batchRunning ||
      show.generationPending || show.batchZipPending || show.displayPending || show.requirementsPending;
    $("translateRequirements").disabled = !show.token || !show.summary.can_translate || show.testPending ||
      show.batchRunning || show.generationPending || show.batchZipPending || show.displayPending || show.requirementsPending;
    $("generateShow").disabled = !(show.token && show.analysis && !show.audioPending &&
      !show.requirementsPending && !show.generationPending && !show.batchRunning &&
      !show.batchZipPending && !show.displayPending && !show.testPending &&
      show.analysisMeter === $("meterSelect").value);
    $("batchFiles").disabled = !show.token || show.batchRunning || show.generationPending ||
      show.batchZipPending || show.displayPending || show.testPending || show.audioPending || show.requirementsPending;
    $("batchLabel").classList.toggle("disabled", !show.token || show.batchRunning || show.generationPending ||
      show.batchZipPending || show.displayPending || show.testPending || show.audioPending || show.requirementsPending);
    setRequirementControlsLocked(show.requirementsPending || show.batchRunning || show.generationPending ||
      show.batchZipPending || show.displayPending || show.testPending);
    $("saveBatch").disabled = !show.batchReady || show.batchRunning || show.batchZipPending ||
      show.generationPending || show.displayPending || show.audioPending || show.requirementsPending ||
      show.testPending;
    updateGeneratedControls();
  }

  async function chooseDisplay(file) {
    if (!file || show.batchRunning || show.batchZipPending || show.generationPending ||
        show.displayPending || show.testPending) return;
    const requestId = ++show.displayRequestId;
    show.displayPending = true;
    setShowConfigurationLocked(true);
    setStepEnabled();
    showMessage("displayStatus", "Reading " + file.name + "…");
    try {
      if (file.size > 20 * 1024 * 1024) throw new Error("A preview must be 20 MiB or smaller.");
      const summary = await postShow("/api/show/start?name=" + encodeURIComponent(file.name),
        await file.text(), "application/xml");
      if (requestId !== show.displayRequestId) return;
      show.token = summary.token;
      show.summary = summary;
      show.test = null;
      show.batchToken = null;
      show.batchConfig = null;
      show.batchReady = false;
      $("saveBatch").disabled = true;
      $("batchList").replaceChildren();
      showMessage("batchStatus", "");
      $("watchTest").disabled = true;
      $("saveTest").disabled = true;
      showMessage("testStatus", "");
      show.analysis = null;
      show.analysisMeter = null;
      show.audioFile = null;
      show.raw = summary.raw_requirements || [];
      show.audioRequestId += 1;
      show.audioPending = false;
      show.requirementsPending = false;
      show.requirementsRequestId += 1;
      invalidateGeneratedResult();
      show.songName = "";
      show.songSeconds = null;
      $("musicFilename").value = "";
      $("songStatus").textContent = "";
      $("musicNote").textContent = "";
      checkMusicName();
      const kinds = summary.kinds.map((kind) => kind.count + " " + kind.label).join(", ");
      const skipped = summary.props.filter((prop) => !prop.sequenceable);
      showMessage("displayStatus", summary.display + ": " + (kinds || "nothing it can sequence") +
        "." + (skipped.length ? " Not sequenced: " + skipped.map((prop) => prop.name +
          (prop.reason ? " (" + prop.reason + ")" : "")).join("; ") + "." : ""), "good");
      fillRequirementForm();
      fillStyles(summary.styles || [], summary.default_style);
      renderRequirements(summary.requirements, []);
      $("singFaces").closest("label").classList.toggle("hidden", !summary.faces);
      $("singNote").textContent = summary.faces ? (summary.can_separate_vocals
        ? "Splitting the vocals out takes a few minutes per song."
        : "Needs the vocals add-on (uv sync --extra vocals); without it the mouths stay still.")
        : "";
      $("plainNote").textContent = summary.can_translate ? ""
        : "Typing requirements in your own words needs a translator (ANTHROPIC_API_KEY); " +
          "use the form instead.";
      if (show.audioFile) await chooseSong(show.audioFile);
    } catch (error) {
      if (requestId !== show.displayRequestId) return;
      showMessage("displayStatus", (error.message || String(error)) +
        (show.token ? " The previously loaded display remains active." : ""), "error");
    }
    if (requestId === show.displayRequestId) {
      show.displayPending = false;
      setShowConfigurationLocked(false);
      setStepEnabled();
    }
  }

  async function chooseSong(file) {
    if (!file || !show.token || show.audioPending || show.batchRunning || show.batchZipPending ||
        show.generationPending || show.displayPending || show.testPending || show.requirementsPending) return;
    const requestId = ++show.audioRequestId;
    const token = show.token;
    const meter = $("meterSelect").value;
    show.audioPending = true;
    showMessage("songStatus", "Analyzing " + file.name + " on this computer…");
    setStepEnabled();
    try {
      if (file.size <= 0 || file.size > 200 * 1024 * 1024) {
        throw new Error("Audio must be non-empty and 200 MiB or smaller.");
      }
      const payload = await withProgress("songStatus", "Sending the song", (key) =>
        postShow("/api/show/audio?token=" + encodeURIComponent(token) +
          "&beats_per_bar=" + meter + "&request_id=" + requestId +
          "&name=" + encodeURIComponent(file.name) + "&progress=" + key, file,
          "application/octet-stream"));
      if (requestId !== show.audioRequestId || token !== show.token || payload.stale) return;
      // Publish the replacement only after analysis and server-side commit succeed.
      // A failed upload leaves the last usable song, analysis and generated result intact.
      show.audioFile = file;
      show.analysis = payload.report;
      show.analysisMeter = meter;
      show.songSeconds = payload.report.audio.duration_seconds;
      show.songName = file.name;
      $("musicFilename").value = file.name;
      checkMusicName();
      invalidateGeneratedResult();
      const analysis = payload.report.analysis;
      const tempo = analysis.tempo && analysis.tempo.bpm != null ? analysis.tempo.bpm + " BPM"
        : "no steady tempo";
      showMessage("songStatus", file.name + ": " + formatTime(payload.report.audio.duration_seconds) +
        ", about " + tempo + ", " + analysis.section_candidates.length + " section changes.",
        "good");
    } catch (error) {
      if (requestId === show.audioRequestId && token === show.token) {
        const previous = show.audioFile
          ? " The previous song (" + show.audioFile.name + ") remains selected and usable."
          : " Choose another song and try again.";
        showMessage("songStatus", (error.message || String(error)) + previous, "error");
        $("showSongFile").value = "";
      }
    } finally {
      if (requestId === show.audioRequestId) {
        show.audioPending = false;
        setStepEnabled();
      }
    }
  }

  function fillStyles(styles, chosen) {
    const box = $("styleChoices");
    box.replaceChildren();
    for (const style of styles) {
      const label = document.createElement("label");
      label.className = "style-choice";
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "showStyle";
      radio.value = style.key;
      radio.checked = style.key === chosen;
      const name = document.createElement("strong");
      name.textContent = style.name;
      const about = document.createElement("span");
      about.textContent = style.description;
      label.append(radio, name, about);
      box.appendChild(label);
    }
  }

  function chosenStyle() {
    const picked = document.querySelector('input[name="showStyle"]:checked');
    return picked ? picked.value : null;
  }

  function option(value, text) {
    const element = document.createElement("option");
    element.value = value;
    element.textContent = text;
    return element;
  }

  function fillRequirementForm() {
    const props = $("requirementProps");
    props.replaceChildren();
    const summary = show.summary;
    for (const kind of summary.kinds) {
      props.appendChild(option("role:" + kind.role, "All " + kind.plural));
    }
    for (const group of summary.groups) props.appendChild(option("group:" + group, "Group: " + group));
    for (const prop of summary.props.filter((item) => item.sequenceable)) {
      props.appendChild(option("name:" + prop.name, prop.name));
    }
    const sections = $("requirementSections");
    sections.replaceChildren();
    for (const name of SECTION_NAMES) {
      const label = document.createElement("label");
      const box = document.createElement("input");
      box.type = "checkbox";
      box.value = name;
      label.append(box, name);
      sections.appendChild(label);
    }
    syncRequirementForm();
  }

  function syncRequirementForm() {
    const kind = $("requirementKind").value;
    $("requirementSections").classList.toggle("hidden", kind !== "quiet_during");
    $("requirementMax").closest("label").classList.toggle("hidden", kind !== "max_intensity");
  }

  function selectorFrom(value) {
    const [kind, ...rest] = value.split(":");
    const text = rest.join(":");
    if (kind === "role") return { role: text };
    if (kind === "group") return { group: text };
    return { names: [text] };
  }

  async function sendRequirements(raw, text) {
    if (!show.token || show.requirementsPending || show.batchRunning || show.generationPending ||
        show.displayPending || show.testPending) return;
    const requestId = ++show.requirementsRequestId;
    show.requirementsPending = true;
    setRequirementControlsLocked(true);
    setStepEnabled();
    try {
      const result = await postShow("/api/show/requirements?token=" +
        encodeURIComponent(show.token) + "&request_id=" + requestId,
        JSON.stringify(text ? { requirements: raw, text } : { requirements: raw }),
        "application/json");
      if (requestId !== show.requirementsRequestId || result.stale) return;
      show.raw = result.raw;
      if (text && $("plainRequirements").value.trim() === text.trim()) {
        $("plainRequirements").value = "";
      }
      invalidateGeneratedResult();
      if (show.batchReady) {
        show.batchReady = false;
        $("saveBatch").disabled = true;
        showMessage("batchStatus", "Requirements changed. Rebuild the playlist before saving it.", "warn");
      }
      renderRequirements(result.requirements, result.problems);
    } catch (error) {
      if (requestId === show.requirementsRequestId) {
        showMessage("requirementStatus", error.message || String(error), "error");
      }
    } finally {
      if (requestId === show.requirementsRequestId) {
        show.requirementsPending = false;
        setRequirementControlsLocked(false);
        setStepEnabled();
      }
    }
  }

  function renderRequirements(described, problems) {
    const list = $("requirementList");
    list.replaceChildren();
    described.forEach((text, index) => {
      const item = document.createElement("li");
      item.textContent = text;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "link-button";
      remove.textContent = "Remove";
      remove.disabled = show.requirementsPending || show.batchRunning || show.generationPending;
      remove.addEventListener("click", () => {
        if (!show.requirementsPending && !show.batchRunning && !show.generationPending) {
          sendRequirements(show.raw.filter((_, other) => other !== index));
        }
      });
      item.appendChild(remove);
      list.appendChild(item);
    });
    showMessage("requirementStatus", (described.length ? described.length +
      " requirement(s), remembered for this display." : "No requirements: the planner decides.") +
      (problems.length ? " " + problems.join(" ") : ""), problems.length ? "warn" : "");
  }

  async function addRequirement() {
    if (show.requirementsPending || show.batchRunning || show.generationPending ||
        show.displayPending || show.testPending) return;
    const kind = $("requirementKind").value;
    const chosen = Array.from($("requirementProps").selectedOptions).map((item) => item.value);
    if (!chosen.length) {
      showMessage("requirementStatus", "Choose which props it is about.", "warn");
      return;
    }
    const added = chosen.map((value) => {
      const item = { type: kind, props: selectorFrom(value) };
      if (kind === "quiet_during") {
        item.sections = Array.from($("requirementSections").querySelectorAll("input:checked"))
          .map((box) => box.value);
      }
      if (kind === "max_intensity") {
        const raw = $("requirementMax").value.trim();
        const maximum = Number(raw);
        if (!raw || !Number.isInteger(maximum) || maximum < 0 || maximum > 100 ||
            maximum % 5 !== 0) {
          showMessage("requirementStatus", "Choose a brightness limit from 0 to 100 in steps of 5.", "warn");
          return null;
        }
        item.max = maximum;
      }
      return item;
    });
    if (kind === "quiet_during" && !added[0].sections.length) {
      showMessage("requirementStatus", "Choose the parts of the song to keep them dark.", "warn");
      return;
    }
    if (added.some((item) => item == null)) return;
    await sendRequirements(show.raw.concat(added));
  }

  async function generateShow() {
    if (show.generationPending || show.batchRunning || show.batchZipPending || show.requirementsPending ||
        show.audioPending || show.displayPending || show.testPending) return;
    const button = $("generateShow");
    const config = currentShowConfig();
    invalidateGeneratedResult();
    show.generationPending = true;
    setShowConfigurationLocked(true);
    setStepEnabled();
    button.disabled = true;
    const singing = $("singFaces").checked && !$("singFaces").closest("label")
      .classList.contains("hidden");
    showMessage("generateStatus", singing
      ? "Splitting the vocals and planning the show; this can take a few minutes…"
      : "Planning the show and checking every rule…");
    try {
      const result = await withProgress("generateStatus", "Starting", (key) =>
        postShow("/api/show/generate?token=" + encodeURIComponent(show.token) + "&progress=" +
          key, JSON.stringify({ music_filename: $("musicFilename").value, sing: singing,
          style: chosenStyle() }), "application/json"));
      if (!result.rules_ok) {
        show.result = null;
        $("openGenerated").disabled = true;
      $("saveGenerated").disabled = true;
        $("pictureGenerated").disabled = true;
        $("showNotes").replaceChildren();
        showMessage("generateStatus", result.report || "The plan did not pass the required rules.",
          "error");
      } else {
        if (config !== currentShowConfig()) {
          throw new Error("The show configuration changed while generation was running. Generate again.");
        }
        show.result = result;
        show.resultConfig = config;
        const parts = result.sections.map((section) => section.label + " (" + section.level + ")");
        showMessage("generateStatus", "Every rule passed. " + (show.songSeconds
          ? "A " + formatTime(show.songSeconds) + " show. " : "") + result.used.length +
          " props used. Click Save show for the .loredit file. Parts: " + parts.join(", ") + "." + (result.skipped.length
          ? " Left out: " + result.skipped.map((item) => item.name + " (" + item.reason + ")")
            .join("; ") + "." : ""), "good");
        $("showNotes").replaceChildren(...result.notes.map((note) => {
        const item = document.createElement("li");
        item.textContent = note;
        return item;
      }));
        $("openGenerated").disabled = false;
        $("saveGenerated").disabled = false;
        $("pictureGenerated").disabled = false;
      $("reportGenerated").disabled = false;
      }
    } catch (error) {
      invalidateGeneratedResult();
      showMessage("generateStatus", error.message || String(error), "error");
    } finally {
      show.generationPending = false;
      setShowConfigurationLocked(false);
      setStepEnabled();
    }
  }

  function resultIsCurrent() {
    return !!show.result && !!show.resultConfig && show.resultConfig === currentShowConfig();
  }

  function saveGenerated() {
    if (generatedActionsBlocked()) return;
    if (!resultIsCurrent() || !show.result.sequence) {
      invalidateGeneratedResult();
      showMessage("generateStatus", "This result no longer matches the selected show settings. Generate it again.", "warn");
      return;
    }
    download(show.result.sequence, show.result.file_name, "application/xml");
  }

  async function openGenerated() {
    const result = show.result;
    if (generatedActionsBlocked()) return;
    if (!resultIsCurrent()) {
      invalidateGeneratedResult();
      showMessage("generateStatus", "This result no longer matches the selected show settings. Generate it again.", "warn");
      return;
    }
    if (!confirmSequenceReplacement()) return;
    openSequenceText(result.sequence, result.file_name, false);
    state.sequence.generated = true;
    state.dirty = true;
    updateEditControls();
    setBanner("Generated " + result.file_name + ". Review it against the music, then Save " +
      "sequence to keep it; open it in S6 to fine-tune.", "good");
    toggleYard(true);
    if (show.audioFile) await loadAudio(show.audioFile, show.analysis, true);
  }

  // Reports and pictures open inside the app (a sandboxed frame with no scripts), so
  // they work the same in a browser tab and in the desktop window.
  function showViewer(title, content, fileName, type) {
    state.viewer = { content, fileName, type };
    $("viewerTitle").textContent = title;
    const html = type === "image/svg+xml"
      ? "<!doctype html><meta charset=\"utf-8\"><body style=\"margin:0;background:#12100e\">" +
        content + "</body>"
      : type === "text/plain"
        ? "<!doctype html><meta charset=\"utf-8\"><pre style=\"margin:0;padding:16px;" +
          "font:12px/1.5 Consolas,monospace;white-space:pre-wrap\">" + escapeHtml(content) + "</pre>"
        : content;
    $("viewerFrame").srcdoc = html;
    $("viewer").classList.remove("hidden");
    $("viewerClose").focus();
  }

  function saveViewer() {
    const viewer = state.viewer;
    if (!viewer) return;
    const url = URL.createObjectURL(new Blob([viewer.content], { type: viewer.type }));
    const link = document.createElement("a");
    link.href = url;
    link.download = viewer.fileName;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  }

  function closeViewer() {
    $("viewer").classList.add("hidden");
    $("viewerFrame").srcdoc = "";
    state.viewer = null;
  }

  function stem(name) {
    return String(name || "show").replace(/\.loredit$/i, "");
  }

  function openReport() {
    if (generatedActionsBlocked() || !resultIsCurrent()) return;
    showViewer("Show report", show.result.summary, stem(show.result.file_name) + ".report.html",
      "text/html");
  }

  function openPicture() {
    if (generatedActionsBlocked() || !resultIsCurrent()) return;
    showViewer("Plan picture", show.result.picture, stem(show.result.file_name) + ".plan.svg",
      "image/svg+xml");
  }

  // A playlist: each song is analyzed and built on the server one at a time, then
  // all the shows are saved together as one zip.
  async function runBatch(files) {
    if (!show.token || !files.length || show.batchRunning || show.batchZipPending || show.generationPending ||
        show.testPending || show.displayPending || show.audioPending || show.requirementsPending) return;
    const batchToken = show.token;
    const batchMeter = $("meterSelect").value;
    const batchStyle = chosenStyle() || "";
    const batchConfig = currentBatchConfig();
    const previousBatchIsUsable = show.batchReady && show.batchToken === batchToken &&
      show.batchConfig === currentBatchConfig();
    show.batchRunning = true;
    setShowConfigurationLocked(true);
    setStepEnabled();
    $("saveBatch").disabled = true;
    try {
      await postShow("/api/show/batch-clear?token=" + encodeURIComponent(batchToken), "{}",
        "application/json");
    } catch (error) {
      // The server keeps the old archive when reset fails. Preserve its UI state too.
      show.batchRunning = false;
      setShowConfigurationLocked(false);
      setStepEnabled();
      $("saveBatch").disabled = !previousBatchIsUsable;
      showMessage("batchStatus", "The previous batch could not be cleared, so no new songs were built: " +
        (error.message || String(error)), "error");
      return;
    }
    show.batchToken = batchToken;
    show.batchConfig = batchConfig;
    show.batchReady = false;
    $("batchList").replaceChildren();
    const rows = files.map((file) => {
      const item = document.createElement("li");
      item.textContent = file.name + ": waiting";
      $("batchList").appendChild(item);
      return item;
    });
    let built = 0;
    let totalSeconds = 0;
    for (let i = 0; i < files.length; i++) {
      if (currentBatchConfig() !== batchConfig || show.token !== batchToken) {
        for (let rest = i; rest < rows.length; rest++) {
          rows[rest].className = "error";
          rows[rest].textContent = files[rest].name + ": not built; show settings changed during the batch";
        }
        break;
      }
      const file = files[i];
      showMessage("batchStatus", "Building " + (i + 1) + " of " + files.length + "…");
      rows[i].textContent = file.name + ": analyzing and building…";
      try {
        const result = await withProgress("batchStatus", "Sending the song", (key) =>
          postShow("/api/show/batch?token=" + encodeURIComponent(batchToken) +
            "&name=" + encodeURIComponent(file.name) + "&beats_per_bar=" +
            batchMeter + "&style=" + encodeURIComponent(batchStyle) +
            "&progress=" + key, file, "application/octet-stream"),
          { from: i / files.length, to: (i + 1) / files.length, last: i === files.length - 1,
            prefix: "Song " + (i + 1) + " of " + files.length + ": " });
        if (result.ok) {
          built += 1;
          totalSeconds += result.duration || 0;
          rows[i].className = "good";
          rows[i].textContent = file.name + ": " + (result.duration ? formatTime(result.duration) +
            ", " : "") + result.parts + " parts, " + result.props + " props";
        } else {
          rows[i].className = "error";
          rows[i].textContent = file.name + ": not built, the plan did not pass the rules";
          rows[i].title = result.problem || "";
        }
      } catch (error) {
        rows[i].className = "error";
        rows[i].textContent = file.name + ": " + (error.message || String(error));
      }
    }
    show.batchRunning = false;
    setShowConfigurationLocked(false);
    setStepEnabled();
    show.batchReady = built > 0 && show.token === batchToken &&
      show.batchConfig === currentBatchConfig();
    $("saveBatch").disabled = !show.batchReady;
    showMessage("batchStatus", built + " of " + files.length + " shows built" +
      (totalSeconds ? ", " + formatTime(totalSeconds) + " of music in all." : ".") +
      (built ? " Save all shows downloads them with their reports." : ""), built ? "good" : "error");
  }

  async function saveBatch() {
    const token = show.batchToken;
    if (show.batchZipPending || show.batchRunning || show.generationPending ||
        show.displayPending || show.audioPending || show.requirementsPending || show.testPending) return;
    if (!show.batchReady || !token || token !== show.token ||
        !show.batchConfig || show.batchConfig !== currentBatchConfig()) {
      $("saveBatch").disabled = true;
      showMessage("batchStatus", "There are no completed shows for the current display. Build the playlist again.", "warn");
      return;
    }
    show.batchZipPending = true;
    setShowConfigurationLocked(true);
    setStepEnabled();
    try {
      const result = await postShow("/api/show/batch-zip?token=" + encodeURIComponent(token),
        "{}", "application/json");
      if (token !== show.token || !show.batchReady || show.batchConfig !== currentBatchConfig()) {
        showMessage("batchStatus", "The playlist changed while it was being packaged. Build it again before saving.", "warn");
        return;
      }
      download(bytesFromBase64(result.zip), result.zip_name, "application/zip");
      showMessage("batchStatus", "Saved " + result.count + " completed show(s) in " + result.zip_name + ".", "good");
    } catch (error) {
      showMessage("batchStatus", error.message || String(error), "error");
    } finally {
      show.batchZipPending = false;
      setShowConfigurationLocked(false);
      setStepEnabled();
    }
  }

  // S6 finds a sequence's music by file name in its own audio folder, so the most
  // common "it plays no music" problem is a name that does not match.
  function checkMusicName() {
    const name = $("musicFilename").value.trim();
    const song = show.songName || "";
    const note = $("musicNote");
    note.className = "step-note";
    if (!name) {
      note.textContent = song ? "Empty: the show will use the song's own name, " + song + "." : "";
      return;
    }
    if (/[\\/]/.test(name)) {
      note.className = "step-note warn";
      note.textContent = "Just the file name, not a folder: S6 looks for it in its own audio folder.";
    } else if (song && name !== song) {
      const sameStem = name.replace(/\.[^.]*$/, "") === song.replace(/\.[^.]*$/, "");
      note.className = "step-note warn";
      note.textContent = sameStem
        ? "The ending differs from your song file (" + song + "). S6 needs the exact name, " +
          "ending included, so convert or rename the song to match."
        : "S6 will look for " + name + ", but your song file is " + song + ". Copy it into " +
          "S6's audio folder under exactly that name, or change this back.";
    } else if (song) {
      note.textContent = "S6 will look for " + name + " in its audio folder. Copy the song " +
        "there under exactly this name.";
    }
  }

  function setupNewShow() {
    $("newShowButton").addEventListener("click", openNewShow);
    $("welcomeNewShow").addEventListener("click", openNewShow);
    $("closeNewShow").addEventListener("click", closeNewShow);
    const bind = (id, handler) => $(id).addEventListener("change", (event) => {
      const file = event.target.files && event.target.files[0];
      if (file) handler(file);
      event.target.value = "";
    });
    bind("showDisplayFile", chooseDisplay);
    bind("showSongFile", chooseSong);
    $("requirementKind").addEventListener("change", syncRequirementForm);
    $("addRequirement").addEventListener("click", addRequirement);
    $("translateRequirements").addEventListener("click", () => {
      const text = $("plainRequirements").value.trim();
      if (text) sendRequirements(show.raw, text);
    });
    $("generateShow").addEventListener("click", generateShow);
    $("makeTest").addEventListener("click", makeDisplayTest);
    $("batchFiles").addEventListener("change", (event) => {
      const files = Array.from(event.target.files || []);
      event.target.value = "";
      runBatch(files);
    });
    $("saveBatch").addEventListener("click", saveBatch);
    $("saveTest").addEventListener("click", saveDisplayTest);
    $("watchTest").addEventListener("click", watchDisplayTest);
    $("musicFilename").addEventListener("input", () => {
      checkMusicName();
      invalidateGeneratedResult();
    });
    $("styleChoices").addEventListener("change", () => {
      invalidateGeneratedResult();
      if (show.batchReady) {
        show.batchReady = false;
        $("saveBatch").disabled = true;
        showMessage("batchStatus", "Show style changed. Rebuild the playlist before saving it.", "warn");
      }
      showMessage("generateStatus", "Show style changed. Generate again to apply it.", "warn");
    });
    $("singFaces").addEventListener("change", () => {
      invalidateGeneratedResult();
    });
    $("openGenerated").addEventListener("click", openGenerated);
    $("saveGenerated").addEventListener("click", saveGenerated);
    $("pictureGenerated").addEventListener("click", openPicture);
    $("reportGenerated").addEventListener("click", openReport);
    $("viewerClose").addEventListener("click", closeViewer);
    $("viewerSave").addEventListener("click", saveViewer);
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !$("viewer").classList.contains("hidden")) closeViewer();
    });
    for (const [value, text] of Object.entries(REQUIREMENT_KINDS)) {
      $("requirementKind").appendChild(option(value, text));
    }
  }

  // ---------------------------------------------------------------------------
  // Yard view: the display drawn from the preview embedded in the sequence, each
  // channel lit by its effects at the playhead. A quick way to watch a show
  // without S6; it approximates the look (shapes are simplified and twinkle is
  // random), and S6's own visualizer stays the reference.

  const COLOR_NAMES = {
    red: "#ff3b30", green: "#30d158", blue: "#2f7bff", white: "#f4f4ee",
    "warm white": "#ffd9a0", "cool white": "#e8f1ff", yellow: "#ffd60a", orange: "#ff9500",
    purple: "#af52de", pink: "#ff5fa2", gold: "#ffc94d", cyan: "#40e0ff", magenta: "#ff40ff",
    amber: "#ffb000", violet: "#8a5cff"
  };

  function colorOf(name) {
    const key = String(name || "").trim().toLowerCase();
    return COLOR_NAMES[key] || "#ffd9a0";
  }

  function numberAttr(node, name) {
    const text = node.getAttribute(name);
    if (text == null || text.trim() === "") return null;
    const value = Number(text);
    return Number.isFinite(value) ? value : null;
  }

  // Split a polyline into ``parts`` pieces of equal length, in order.
  function splitLine(points, parts) {
    if (parts <= 1 || points.length < 2) return [points];
    const lengths = [0];
    for (let i = 1; i < points.length; i++) {
      lengths.push(lengths[i - 1] + Math.hypot(points[i][0] - points[i - 1][0],
        points[i][1] - points[i - 1][1]));
    }
    const total = lengths[lengths.length - 1] || 1;
    const at = (distance) => {
      let i = 1;
      while (i < lengths.length - 1 && lengths[i] < distance) i++;
      const span = lengths[i] - lengths[i - 1] || 1;
      const share = (distance - lengths[i - 1]) / span;
      return [points[i - 1][0] + (points[i][0] - points[i - 1][0]) * share,
        points[i - 1][1] + (points[i][1] - points[i - 1][1]) * share];
    };
    const pieces = [];
    for (let part = 0; part < parts; part++) {
      const from = total * part / parts;
      const to = total * (part + 1) / parts;
      const piece = [at(from)];
      for (let i = 1; i < points.length - 1; i++) {
        if (lengths[i] > from && lengths[i] < to) piece.push(points[i]);
      }
      piece.push(at(to));
      pieces.push(piece);
    }
    return pieces;
  }

  // Strands for a shape drawn in a box: an arch, a tree, a star, a snowflake...
  function boxStrands(shapeName, cx, cy, w, h, radians, channels) {
    const name = shapeName.toLowerCase();
    const rotate = (points) => points.map(([x, y]) => {
      const dx = x - cx;
      const dy = y - cy;
      return [cx + dx * Math.cos(radians) - dy * Math.sin(radians),
        cy + dx * Math.sin(radians) + dy * Math.cos(radians)];
    });
    if (name.includes("tree")) {
      // Strands fan from the top down to the base, one per channel.
      const strands = [];
      for (let i = 0; i < channels; i++) {
        const share = channels === 1 ? 0.5 : i / (channels - 1);
        strands.push(rotate([[cx, cy + h / 2], [cx - w / 2 + w * share, cy - h / 2]]));
      }
      if (channels === 1) {
        return [rotate([[cx - w / 2, cy - h / 2], [cx, cy + h / 2], [cx + w / 2, cy - h / 2],
          [cx - w / 2, cy - h / 2]])];
      }
      return strands;
    }
    let outline;
    if (name.includes("arch")) {
      outline = [];
      for (let k = 0; k <= 24; k++) {
        const angle = Math.PI * (1 - k / 24);
        outline.push([cx + Math.cos(angle) * w / 2, cy - h / 2 + Math.sin(angle) * h]);
      }
    } else if (name.includes("star")) {
      outline = [];
      for (let k = 0; k <= 10; k++) {
        const radius = k % 2 === 0 ? 1 : 0.45;
        const angle = Math.PI / 2 + Math.PI * k / 5;
        outline.push([cx + Math.cos(angle) * radius * w / 2, cy + Math.sin(angle) * radius * h / 2]);
      }
    } else if (name.includes("snow") || name.includes("flake")) {
      const arms = [];
      for (let k = 0; k < 6; k++) {
        const angle = Math.PI * k / 3 + Math.PI / 2;
        arms.push(rotate([[cx, cy], [cx + Math.cos(angle) * w / 2, cy + Math.sin(angle) * h / 2]]));
      }
      if (channels <= 1) return [arms.flat()];
      // Channels light the flake from the center out: inner, then outer parts of every arm.
      const strands = [];
      for (let i = 0; i < channels; i++) {
        strands.push(arms.flatMap((arm) => splitLine(arm, channels)[i]));
      }
      return strands;
    } else if (/circle|wreath|ball|ring|round|candy/.test(name)) {
      outline = [];
      for (let k = 0; k <= 32; k++) {
        const angle = 2 * Math.PI * k / 32;
        outline.push([cx + Math.cos(angle) * w / 2, cy + Math.sin(angle) * h / 2]);
      }
    } else {
      outline = [[cx - w / 2, cy - h / 2], [cx - w / 2, cy + h / 2], [cx + w / 2, cy + h / 2],
        [cx + w / 2, cy - h / 2], [cx - w / 2, cy - h / 2]];
    }
    return splitLine(rotate(outline), channels);
  }

  function pointStrands(shapeName, points, channels) {
    if (/unconnected/i.test(shapeName)) {
      const segments = [];
      for (let i = 0; i + 1 < points.length; i += 2) segments.push([points[i], points[i + 1]]);
      if (!segments.length) return [];
      if (channels <= 1) return [segments.flat()];
      const strands = [];
      for (let i = 0; i < channels; i++) {
        const from = Math.floor(segments.length * i / channels);
        const to = Math.max(from + 1, Math.floor(segments.length * (i + 1) / channels));
        strands.push(segments.slice(from, to).flat());
      }
      return strands;
    }
    return splitLine(points, channels);
  }

  // Read the preview that S6 keeps inside the sequence into drawable props.
  function parseYard(doc) {
    const preview = doc.documentElement.querySelector(":scope > PreviewClass");
    if (!preview) return null;
    const yard = [];
    for (const node of preview.children) {
      if (node.localName !== "PropClass") continue;
      const shape = Array.from(node.children).find((child) => child.localName === "shape");
      if (!shape) continue;
      const grid = (node.getAttribute("ChannelGrid") || "").split(";").filter(Boolean)
        .map((entry) => entry.split(","));
      const channels = Math.max(1, grid.length);
      const traditional = (node.getAttribute("TraditionalColors") || "").split(",")
        .map((item) => item.trim()).filter(Boolean);
      const colors = grid.map((entry, index) => {
        const named = (entry[5] || "").trim();
        if (/^multi/i.test(named)) return traditional.length > 1 ? traditional : ["Red", "Green"];
        return [named || traditional[index] || traditional[0] || "Warm White"];
      });
      const shapeName = shape.getAttribute("ShapeName") || "";
      const points = Array.from(shape.children).filter((child) => child.localName === "point")
        .map((point) => [numberAttr(point, "x"), numberAttr(point, "y")])
        .filter(([x, y]) => x != null && y != null);
      const cx = numberAttr(shape, "OffsetX");
      const cy = numberAttr(shape, "OffsetY");
      const w = numberAttr(shape, "ScaleX");
      const h = numberAttr(shape, "ScaleY");
      let strands = [];
      if (cx != null && cy != null && w != null && h != null) {
        strands = boxStrands(shapeName, cx, cy, Math.abs(w), Math.abs(h),
          numberAttr(shape, "Radians") || 0, channels);
      } else if (points.length >= 2) {
        strands = pointStrands(shapeName, points, channels);
      }
      if (!strands.length) continue;
      yard.push({ id: node.getAttribute("id") || "", name: node.getAttribute("Name") || "",
        strands, colors: colors.length ? colors : [traditional.length ? traditional : ["Warm White"]],
        pixel: /dmx|rgb|pixel/i.test((node.getAttribute("DeviceType") || "") + " " +
          (node.getAttribute("StringType") || "")) });
    }
    if (!yard.length) return null;
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const prop of yard) {
      for (const strand of prop.strands) {
        for (const [x, y] of strand) {
          minX = Math.min(minX, x);
          maxX = Math.max(maxX, x);
          minY = Math.min(minY, y);
          maxY = Math.max(maxY, y);
        }
      }
    }
    return { props: yard, bounds: { minX, minY, maxX, maxY } };
  }

  // A channel's brightness (0..1) at a time, from its effects.
  function channelLevel(channel, cs) {
    if (!channel.sortedFor || channel.sortedFor !== channel.effects) {
      channel.sorted = channel.effects.slice().sort((a, b) => a.start - b.start);
      channel.sortedFor = channel.effects;
    }
    const list = channel.sorted;
    let low = 0;
    let high = list.length - 1;
    let found = -1;
    while (low <= high) {
      const middle = (low + high) >> 1;
      if (list[middle].start <= cs) {
        found = middle;
        low = middle + 1;
      } else {
        high = middle - 1;
      }
    }
    let level = 0;
    for (let i = found; i >= 0 && i > found - 4; i--) {
      const effect = list[i];
      if (effect.end <= cs) continue;
      const attrs = effect.attributes;
      let value;
      if (attrs.startIntensity != null && attrs.endIntensity != null) {
        const share = (cs - effect.start) / Math.max(1, effect.end - effect.start);
        value = Number(attrs.startIntensity) +
          (Number(attrs.endIntensity) - Number(attrs.startIntensity)) * share;
      } else {
        value = Number(attrs.intensity != null ? attrs.intensity : 100);
      }
      if (effect.type === "TWINKLE" || effect.type === "SHIMMER") {
        const step = effect.type === "SHIMMER" ? 4 : 12;
        const seed = Math.sin((Math.floor(cs / step) + 1) * 12.9898 + effect.start * 0.0781) * 43758.5;
        value *= 0.35 + 0.65 * (seed - Math.floor(seed));
      }
      level = Math.max(level, (Number.isFinite(value) ? value : 0) / 100);
    }
    return Math.max(0, Math.min(1, level));
  }

  function yardVisible() {
    return Boolean(state.sequence && state.yardOpen && !$("yardPanel").classList.contains("hidden"));
  }

  function drawYard(seconds) {
    if (!yardVisible()) return;
    const canvas = $("yardCanvas");
    const yard = state.sequence.yard;
    const box = canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.round(box.width * ratio));
    const height = Math.max(1, Math.round(box.height * ratio));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#05080c";
    ctx.fillRect(0, 0, width, height);
    if (!yard) {
      ctx.fillStyle = "#958a7c";
      ctx.font = 13 * ratio + "px Segoe UI, sans-serif";
      ctx.fillText("This sequence has no preview inside it, so the yard cannot be drawn.",
        16 * ratio, 28 * ratio);
      return;
    }
    const { minX, minY, maxX, maxY } = yard.bounds;
    const pad = 0.06;
    const spanX = Math.max(1e-6, maxX - minX);
    const spanY = Math.max(1e-6, maxY - minY);
    const scale = Math.min(width * (1 - 2 * pad) / spanX, height * (1 - 2 * pad) / spanY);
    const offsetX = (width - spanX * scale) / 2;
    const offsetY = (height - spanY * scale) / 2;
    const toX = (x) => offsetX + (x - minX) * scale;
    const toY = (y) => height - (offsetY + (y - minY) * scale);
    const cs = Math.round(seconds * 100);
    const byId = state.sequence.propsById || (state.sequence.propsById =
      new Map(state.sequence.props.map((prop) => [prop.id, prop])));
    const line = Math.max(1.5, 2.2 * ratio);
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    let lit = 0;
    for (const prop of yard.props) {
      const sequenced = byId.get(prop.id);
      prop.strands.forEach((strand, index) => {
        const channel = sequenced && sequenced.channels[index];
        const level = channel ? channelLevel(channel, cs) : 0;
        const colors = prop.colors[Math.min(index, prop.colors.length - 1)] || ["Warm White"];
        ctx.beginPath();
        strand.forEach(([x, y], k) => {
          if (k === 0) ctx.moveTo(toX(x), toY(y));
          else ctx.lineTo(toX(x), toY(y));
        });
        // Unlit strands stay faintly visible so the layout reads.
        ctx.globalAlpha = 0.14 + 0.86 * level;
        ctx.lineWidth = line;
        ctx.shadowBlur = level > 0.05 ? 14 * ratio * level : 0;
        if (colors.length > 1) {
          // Multicolor strings: alternate the colors along the strand.
          colors.forEach((name, c) => {
            ctx.setLineDash([5 * ratio, 5 * ratio * (colors.length - 1)]);
            ctx.lineDashOffset = -c * 5 * ratio;
            ctx.strokeStyle = colorOf(name);
            ctx.shadowColor = colorOf(name);
            ctx.stroke();
          });
          ctx.setLineDash([]);
        } else {
          ctx.strokeStyle = level > 0 ? colorOf(colors[0]) : "#6a6157";
          ctx.shadowColor = colorOf(colors[0]);
          ctx.stroke();
        }
        if (level > 0.05) lit += 1;
      });
    }
    ctx.globalAlpha = 1;
    ctx.shadowBlur = 0;
    $("yardStatus").textContent = formatCentiseconds(cs) + " · " + lit + " channel(s) lit";
    // For tests and support: what was drawn.
    canvas.dataset.props = String(yard.props.length);
    canvas.dataset.lit = String(lit);
    canvas.dataset.bounds = [minX, minY, maxX, maxY].map((v) => v.toFixed(3)).join(",");
  }

  function toggleYard(open) {
    state.yardOpen = open == null ? !state.yardOpen : open;
    $("yardPanel").classList.toggle("hidden", !state.yardOpen);
    $("yardButton").classList.toggle("active", state.yardOpen);
    $("yardButton").setAttribute("aria-pressed", String(state.yardOpen));
    if (state.yardOpen) drawYard(yardSeconds());
  }

  // The yard lives in the workspace. From New show, it opens the generated show there;
  // with nothing to play yet, it says what to do instead of doing nothing.
  function yardButtonClicked() {
    if (!$("newShow").classList.contains("hidden")) {
      if (generatedActionsBlocked()) {
        showMessage("generateStatus", "Wait for the current show operation to finish before opening Yard view.", "warn");
        $("generateStatus").scrollIntoView({ block: "center" });
      } else if (resultIsCurrent()) {
        openGenerated();
      } else {
        showMessage("generateStatus", "Generate a show first; Yard view then plays it on a " +
          "drawing of your display.", "error");
        $("generateStatus").scrollIntoView({ block: "center" });
      }
      return;
    }
    if (!state.sequence) {
      setBanner("Open a sequence or make a New show first; Yard view plays it on a drawing " +
        "of the display.", "error");
      return;
    }
    toggleYard();
  }

  function yardSeconds() {
    return state.audioBuffer && Number.isFinite(audio.currentTime) ? audio.currentTime
      : (state.cursorCs || 0) / 100;
  }

  function setupYard() {
    $("yardButton").addEventListener("click", yardButtonClicked);
    window.addEventListener("resize", () => drawYard(yardSeconds()));
  }

  // The landing page's hero: an invented yard lit to a 112 BPM beat, the same way a
  // generated show lights a real one (arches chase, snowflakes fall, the tree spins).
  const HERO_BEAT = 60 / 112;
  const BULB = { red: "232,69,60", green: "63,174,106", gold: "242,180,65", white: "255,236,205",
    blue: "110,170,255" };

  function heroScene() {
    const arches = [0.075, 0.185, 0.295].map((cx) => {
      const bulbs = [];
      for (let k = 0; k <= 10; k++) {
        const a = Math.PI * (1 - k / 10);
        bulbs.push([cx + 0.048 * Math.cos(a), 0.88 - 0.2 * Math.sin(a)]);
      }
      return bulbs;
    });
    const tree = [];
    for (let strand = 0; strand < 12; strand++) {
      const bulbs = [];
      for (let k = 1; k <= 11; k++) {
        const along = k / 11;
        bulbs.push([0.5 + (strand / 11 - 0.5) * 0.2 * along, 0.24 + 0.64 * along]);
      }
      tree.push(bulbs);
    }
    const minis = [0.385, 0.615].map((cx) => {
      const bulbs = [];
      for (let k = 0; k < 8; k++) {
        const along = k / 7;
        bulbs.push([cx - 0.026 * along, 0.72 + 0.16 * along], [cx + 0.026 * along, 0.72 + 0.16 * along]);
      }
      return bulbs;
    });
    const flakes = [];
    for (const x of [0.09, 0.19, 0.29]) {
      for (const [row, y] of [0.13, 0.3, 0.47].entries()) flakes.push({ x, y, row });
    }
    const house = [];
    const outline = [[0.7, 0.88], [0.7, 0.52], [0.675, 0.52], [0.835, 0.26], [0.995, 0.52],
      [0.97, 0.52], [0.97, 0.88]];
    for (let i = 0; i < outline.length - 1; i++) {
      const [x1, y1] = outline[i];
      const [x2, y2] = outline[i + 1];
      const n = Math.max(2, Math.round(Math.hypot(x2 - x1, y2 - y1) / 0.018));
      for (let k = 0; k < n; k++) house.push([x1 + (x2 - x1) * k / n, y1 + (y2 - y1) * k / n]);
    }
    return { arches, tree, minis, flakes, house };
  }

  function drawHero(canvas, scene, t) {
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return;
    const ratio = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(width * ratio)) {
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const beats = t / HERO_BEAT;
    const beat = Math.floor(beats);
    const inBeat = beats - beat;
    const bar = Math.floor(beat / 4);
    const flash = beat % 16 === 0 && inBeat < 0.25 ? 1 - inBeat * 4 : 0;
    const pulse = Math.exp(-inBeat * 5);
    const unit = width / 400;
    const bulb = (x, y, color, level, size) => {
      const v = Math.min(1, Math.max(level, flash * 0.9));
      ctx.fillStyle = "rgba(" + color + "," + (0.12 + 0.88 * v).toFixed(3) + ")";
      ctx.shadowColor = "rgba(" + color + "," + v.toFixed(3) + ")";
      ctx.shadowBlur = 16 * v * unit;
      ctx.beginPath();
      ctx.arc(x * width, y * height, size * unit * (0.8 + 0.4 * v), 0, Math.PI * 2);
      ctx.fill();
    };
    ctx.strokeStyle = "rgba(255,236,205,.08)";
    ctx.beginPath();
    ctx.moveTo(0, 0.895 * height);
    ctx.lineTo(width, 0.895 * height);
    ctx.stroke();
    // Outlines: the steady base, a little brighter on each bar.
    const base = 0.55 + 0.35 * Math.exp(-((beats % 4) * 1.5));
    for (const [x, y] of scene.house) bulb(x, y, BULB.white, base, 1.7);
    // Arches chase one per beat, left to right.
    scene.arches.forEach((bulbs, i) => {
      const level = beat % 3 === i ? 0.35 + 0.65 * pulse : 0.05;
      for (const [x, y] of bulbs) bulb(x, y, i % 2 ? BULB.green : BULB.red, level, 2.2);
    });
    // Mini trees trade beats: outer pair, then inner pair.
    scene.minis.forEach((bulbs, i) => {
      const level = (beat % 2 === 0) === (i === 0) ? 0.3 + 0.7 * pulse : 0.06;
      for (const [x, y] of bulbs) bulb(x, y, BULB.green, level, 2);
    });
    // The mega tree spins: a band of strands rotating once a bar.
    const turn = (beats / 4) % 1;
    scene.tree.forEach((bulbs, strand) => {
      const spot = Math.abs(((strand / 12 - turn) % 1 + 1) % 1 - 0.5) * 2;
      const level = Math.max(0.08, Math.pow(spot, 3));
      for (const [x, y] of bulbs) bulb(x, y, strand % 2 ? BULB.red : BULB.white, level, 1.8);
    });
    bulb(0.5, 0.215, BULB.gold, 0.85 + 0.15 * Math.sin(t * 3), 4.5);
    // Snowflakes fall: top row, middle, bottom, on the eighth notes, fading as they go.
    const step = Math.floor(beats * 2);
    for (const flake of scene.flakes) {
      const since = ((step - flake.row) % 4 + 4) % 4;
      const level = since === 0 ? 1 - ((beats * 2) % 1) * 0.5 : since === 1 ? 0.25 : 0.05;
      const cx = flake.x * width;
      const cy = flake.y * height;
      const r = Math.min(width, height) * 0.06;
      const v = Math.max(level, flash * 0.9);
      ctx.strokeStyle = "rgba(" + BULB.blue + "," + (0.12 + 0.88 * v).toFixed(3) + ")";
      ctx.shadowColor = "rgba(" + BULB.blue + "," + v.toFixed(3) + ")";
      ctx.shadowBlur = 12 * v * unit;
      ctx.lineWidth = 1.2 * unit;
      ctx.beginPath();
      for (let arm = 0; arm < 6; arm++) {
        const a = arm * Math.PI / 3;
        ctx.moveTo(cx, cy);
        ctx.lineTo(cx + r * Math.cos(a), cy + r * Math.sin(a));
      }
      ctx.stroke();
    }
    ctx.shadowBlur = 0;
    canvas.dataset.bar = String(bar);
  }

  function setupHero() {
    const canvas = $("heroYard");
    if (!canvas || !canvas.getContext) return;
    const scene = heroScene();
    const still = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const started = performance.now();
    const frame = (now) => {
      if (!$("welcome").classList.contains("hidden")) drawHero(canvas, scene, (now - started) / 1000);
      if (!still) requestAnimationFrame(frame);
    };
    if (still) {
      drawHero(canvas, scene, HERO_BEAT * 1.05);
      window.addEventListener("resize", () => drawHero(canvas, scene, HERO_BEAT * 1.05));
    } else {
      requestAnimationFrame(frame);
    }
  }

  // Once per start, ask the local server whether a newer release is on GitHub. People
  // can stop it ("Stop checking"); a manual check on the landing page still works.
  const UPDATE_KEY = "lorSequencer.updateCheck";

  function updatePreference() {
    try { return window.localStorage.getItem(UPDATE_KEY); } catch { return null; }
  }

  function setUpdatePreference(value) {
    try {
      if (value) window.localStorage.setItem(UPDATE_KEY, value);
      else window.localStorage.removeItem(UPDATE_KEY);
    } catch { /* storage unavailable: the choice lasts until the window closes */ }
  }

  async function checkForUpdate(manual) {
    if (!manual && updatePreference() === "off") return;
    if (manual) $("versionText").textContent = "Checking…";
    let result;
    try {
      result = await postShow("/api/update", "", "application/json");
    } catch (error) {
      result = { error: error.message || String(error) };
    }
    if (result.current) $("versionText").textContent = "Version " + result.current;
    if (result.newer && result.latest) {
      if (!manual && updatePreference() === "skip:" + result.latest) return;
      $("updateText").textContent = "LOR Sequencer " + result.latest + " is out (you have " +
        result.current + ").";
      $("updateLink").href = result.installer || result.page;
      $("updateLink").textContent = result.installer ? "Download the installer" : "See what's new";
      $("updateBar").dataset.latest = result.latest;
      $("updateBar").classList.remove("hidden");
    } else if (manual) {
      $("versionText").textContent = "Version " + (result.current || "") + (result.error
        ? " (could not reach GitHub)" : result.disabled ? " (update checks are off)"
          : " (up to date)");
    }
  }

  function setupUpdates() {
    $("updateLater").addEventListener("click", () => {
      setUpdatePreference("skip:" + ($("updateBar").dataset.latest || ""));
      $("updateBar").classList.add("hidden");
    });
    $("updateOff").addEventListener("click", () => {
      setUpdatePreference("off");
      $("updateBar").classList.add("hidden");
    });
    $("checkUpdates").addEventListener("click", () => {
      setUpdatePreference(null);
      checkForUpdate(true);
    });
    checkForUpdate(false);
  }

  // Help when something "does nothing": page errors go to the local log, the last
  // few clicks are kept in memory, and Copy diagnostics gathers both with the
  // version and system checks for pasting into a message.
  const steps = [];

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" })[c]);
  }

  function remember(step) {
    steps.push(new Date().toISOString().slice(11, 19) + " " + step);
    if (steps.length > 60) steps.shift();
  }

  function logProblem(message, where) {
    remember("problem: " + String(message).slice(0, 160));
    fetch("/api/log", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: String(message).slice(0, 1500), where }) }).catch(() => {});
  }

  async function copyDiagnostics() {
    $("copyDiagnostics").textContent = "Gathering…";
    try {
      const result = await postShow("/api/diagnostics",
        JSON.stringify({ browser: navigator.userAgent, steps }), "application/json");
      showViewer("Diagnostics", result.text, "LOR Sequencer diagnostics.txt", "text/plain");
      let copied = false;
      try {
        await navigator.clipboard.writeText(result.text);
        copied = true;
      } catch { /* the viewer still shows it, with Save a copy */ }
      $("viewerTitle").textContent = copied
        ? "Diagnostics (copied: paste it into your message)"
        : "Diagnostics (select it all and copy, or Save a copy)";
    } catch (error) {
      setBanner("Diagnostics could not be gathered: " + (error.message || String(error)), "warn");
    }
    $("copyDiagnostics").textContent = "Copy diagnostics";
  }

  function setupDiagnostics() {
    window.addEventListener("error", (event) => logProblem(event.message,
      (event.filename || "").split("/").pop() + ":" + event.lineno));
    window.addEventListener("unhandledrejection", (event) => logProblem(
      event.reason && event.reason.message ? event.reason.message : String(event.reason),
      "promise"));
    document.addEventListener("click", (event) => {
      const target = event.target.closest && event.target.closest("button, label, a");
      if (!target) return;
      const name = target.id || (target.querySelector("input") || {}).id ||
        (target.textContent || "").trim().slice(0, 30);
      remember("click " + name + (target.disabled ? " (disabled)" : ""));
    }, true);
    document.addEventListener("change", (event) => {
      if (event.target.type === "file" && event.target.files && event.target.files[0]) {
        remember("chose a file for " + event.target.id);
      }
    }, true);
    $("copyDiagnostics").addEventListener("click", copyDiagnostics);
  }

  // Progress for anything that takes more than a moment: a bar, what the program is
  // doing now (as the engine reports it) and the time so far, under the status line.
  // `run` gets a key to send as &progress=KEY; quick jobs finish before it appears.
  function newProgressKey() {
    const bytes = new Uint8Array(8);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  }

  function progressBox(anchorId) {
    const id = anchorId + "Progress";
    let box = $(id);
    if (!box) {
      box = document.createElement("div");
      box.id = id;
      box.className = "progress hidden";
      box.setAttribute("role", "progressbar");
      box.setAttribute("aria-valuemin", "0");
      box.setAttribute("aria-valuemax", "100");
      box.innerHTML = '<div class="progress-track"><span class="progress-fill"></span></div>' +
        '<div class="progress-text"></div>';
      $(anchorId).insertAdjacentElement("afterend", box);
    }
    return box;
  }

  function seconds(value) {
    const total = Math.round(value);
    return total < 60 ? total + " s" : formatTime(total);
  }

  async function withProgress(anchorId, firstStep, run, scale) {
    const key = newProgressKey();
    const box = progressBox(anchorId);
    const fill = box.querySelector(".progress-fill");
    const text = box.querySelector(".progress-text");
    const started = performance.now();
    const range = scale || { from: 0, to: 1, prefix: "" };
    let stopped = false;
    const paint = (fraction, step, slow, elapsed) => {
      const shown = range.from + (range.to - range.from) * Math.max(0, Math.min(1, fraction));
      fill.style.width = Math.round(shown * 100) + "%";
      box.setAttribute("aria-valuenow", String(Math.round(shown * 100)));
      box.classList.toggle("slow", Boolean(slow));
      text.textContent = range.prefix + step + "… " + seconds(elapsed) +
        (slow ? " so far. This part takes a few minutes; it is still working." : "");
    };
    const poll = async () => {
      while (!stopped) {
        await new Promise((resolve) => setTimeout(resolve, 400));
        if (stopped) break;
        const elapsed = (performance.now() - started) / 1000;
        box.classList.remove("hidden");
        try {
          const state = await callEngine("/api/progress?key=" + key, "{}", "application/json");
          if (stopped) break;
          if (state.known) paint(state.fraction, state.step, state.slow, elapsed);
          else paint(0, firstStep, false, elapsed);
        } catch {
          paint(0, firstStep, false, elapsed);
        }
      }
    };
    paint(0, firstStep, false, 0);
    const polling = poll();
    try {
      return await run(key);
    } finally {
      stopped = true;
      await polling.catch(() => {});
      if (!scale || scale.last) box.classList.add("hidden");
    }
  }

  // Started from a preview (right-click "Build a show with LOR Sequencer"): open New
  // show with that display already chosen.
  async function openStartupPreview() {
    if (new URLSearchParams(window.location.search).get("start") !== "preview") return;
    try { window.history.replaceState(null, "", window.location.pathname); } catch { /* fine */ }
    try {
      const startup = await callEngine("/api/startup", "{}", "application/json");
      if (!startup.preview) return;
      openNewShow();
      await chooseDisplay(new File([startup.preview.text], startup.preview.name,
        { type: "application/xml" }));
    } catch (error) {
      setBanner("That preview could not be opened: " + problemText(error), "error");
    }
  }

  function setup() {
    const bindFile = (id, handler) => $(id).addEventListener("change", (event) => {
      const file = event.target.files && event.target.files[0];
      if (file) handler(file);
      event.target.value = "";
    });
    bindFile("sequenceFile", loadSequence);
    bindFile("welcomeSequenceFile", loadSequence);
    bindFile("audioFile", loadAudio);
    bindFile("welcomeAudioFile", loadAudio);
    bindFile("analysisFile", loadAnalysis);
    bindFile("vocalsFile", loadVocals);
    bindFile("lyricsFile", loadLyrics);

    $("zoomSlider").addEventListener("input", (event) => {
      const centerTime = state.sequence
        ? (canvasViewport.scrollLeft + canvasViewport.clientWidth / 2) / state.pxPerSecond
        : 0;
      state.pxPerSecond = Number(event.target.value);
      refreshTimeline();
      if (state.sequence) {
        canvasViewport.scrollLeft = Math.max(0,
          centerTime * state.pxPerSecond - canvasViewport.clientWidth / 2);
      }
    });
    $("fitButton").addEventListener("click", () => {
      if (!state.sequence) return;
      const available = Math.max(1, canvasViewport.clientWidth - 20);
      const duration = getTimelineDurationSeconds();
      const minimum = Number($("zoomSlider").min);
      const maximum = Number($("zoomSlider").max);
      state.pxPerSecond = Math.max(minimum, Math.min(maximum, available / duration));
      $("zoomSlider").value = String(state.pxPerSecond);
      refreshTimeline();
      canvasViewport.scrollLeft = 0;
    });
    $("meterSelect").addEventListener("change", () => {
      if (show.token) invalidateGeneratedResult();
      if (show.batchReady && show.batchConfig !== currentBatchConfig()) {
        show.batchReady = false;
        $("saveBatch").disabled = true;
        showMessage("batchStatus", "Meter changed. Rebuild the playlist before saving it.", "warn");
      }
      if (show.token && show.audioFile && !show.batchRunning && !show.generationPending) {
        chooseSong(show.audioFile);
      }
      if (state.reviewDirty) {
        setBanner("Meter set to " + $("meterSelect").value + "/4 for fitting bars. Your saved music review is kept.", "good");
        return;
      }
      if (state.audioFile && state.audioBuffer) analyzeSelectedAudio(state.audioFile);
    });
    $("playButton").addEventListener("click", async () => {
      const requestedFile = state.audioFile;
      if (!requestedFile) return;
      if (audio.paused) {
        try {
          await audio.play();
          // The user may have stopped playback or replaced the song while the
          // browser was resolving play(). Never let that stale continuation
          // restore the playing icon or animation.
          if (audio.paused || state.audioFile !== requestedFile) return;
          $("playButton").textContent = "Ⅱ";
          cancelAnimationFrame(state.animationFrame);
          state.animationFrame = requestAnimationFrame(tickPlayback);
        } catch (error) {
          if (state.audioFile === requestedFile) {
            setBanner("Audio playback could not start: " + (error.message || String(error)), "warn");
          }
        }
      } else {
        audio.pause();
        $("playButton").textContent = "▶";
      }
    });
    $("stopButton").addEventListener("click", () => {
      audio.pause();
      audio.currentTime = 0;
      $("playButton").textContent = "▶";
      updatePlayhead();
    });
    audio.addEventListener("ended", () => $("playButton").textContent = "▶");
    audio.addEventListener("pause", () => $("playButton").textContent = "▶");
    audio.addEventListener("timeupdate", updatePlayhead);
    canvasViewport.addEventListener("scroll", syncScroll);
    window.addEventListener("resize", () => {
      if (state.sequence) refreshTimeline();
    });
    $("waveformCanvas").addEventListener("click", (event) => seekFromPointer(event, $("waveformCanvas")));
    setupEditing();
    setupNewShow();
    setupYard();
    setupHero();
    setupUpdates();
    setupDiagnostics();
    openStartupPreview();
  }

  setup();
})();