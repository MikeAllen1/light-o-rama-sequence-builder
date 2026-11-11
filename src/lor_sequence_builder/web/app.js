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
  const MAX_XML_DEPTH = 256;

  const state = {
    sequence: null,
    audioFile: null,
    audioBuffer: null,
    waveformPeaks: null,
    audioUrl: null,
    analysis: null,
    vocals: null,
    rows: [],
    lanes: [],
    pxPerSecond: 22,
    collapsedGroups: new Set(),
    collapsedProps: new Set(),
    selectedEffect: null,
    animationFrame: 0
  };

  const audio = $("audioPlayer");
  const canvasViewport = $("canvasViewport");
  const labelsViewport = $("labelsViewport");
  const playhead = $("playhead");

  function setBanner(message, kind) {
    const banner = $("analysisBanner");
    $("analysisMessage").textContent = message;
    banner.className = "analysis-banner" + (kind ? " " + kind : "");
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
          effects: []
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
      if (groupId && groupIds.has(groupId)) propsByGroup.get(groupId).push(prop);
      else ungrouped.push(prop);
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

  function buildLanes() {
    const lanes = [];
    for (const grid of state.sequence ? state.sequence.timingGrids : []) {
      let marks = grid.marks;
      if (grid.kind === "fixed" && grid.spacing > 0) {
        const count = Math.min(50000, Math.floor(state.sequence.durationCs / grid.spacing) + 1);
        marks = Array.from({ length: count }, (_, index) => index * grid.spacing);
      }
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
        label: "Estimated beats", source: "librosa", kind: "beats", events: analysis.beats
      });
      if (analysis.downbeats && analysis.downbeats.length) lanes.push({
        label: "Estimated downbeats", source: "librosa", kind: "downbeats", events: analysis.downbeats
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
    }
    if (state.vocals) {
      if (state.vocals.regions && state.vocals.regions.length) lanes.push({
        label: "Vocal regions", source: "heuristic", kind: "vocal-regions", events: state.vocals.regions
      });
      if (state.vocals.syllables && state.vocals.syllables.length) lanes.push({
        label: "Syllable onsets", source: "heuristic", kind: "syllables", events: state.vocals.syllables
      });
    }
    state.lanes = lanes;
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
      badge.textContent = source + (average == null ? "" : " · " + average.toFixed(2));
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

  function drawRuler(width, duration, pps) {
    const canvas = $("rulerCanvas");
    const ctx = setCanvasSize(canvas, width, RULER_HEIGHT);
    ctx.fillStyle = "#1a2530";
    ctx.fillRect(0, 0, width, RULER_HEIGHT);
    const step = pps < 14 ? 10 : pps < 25 ? 5 : 2;
    ctx.font = "10px Segoe UI, sans-serif";
    for (let second = 0; second <= duration; second += 1) {
      const x = second * pps;
      const major = second % step === 0;
      ctx.strokeStyle = major ? "#586978" : "#2e3c48";
      ctx.beginPath();
      ctx.moveTo(Math.floor(x) + .5, major ? 13 : 25);
      ctx.lineTo(Math.floor(x) + .5, RULER_HEIGHT);
      ctx.stroke();
      if (major) {
        ctx.fillStyle = "#a8b6c2";
        ctx.fillText(formatTime(second), x + 4, 11);
      }
    }
    const bars = state.sequence.timingGrids.find((grid) => /^bars?$/i.test(grid.name));
    if (bars) {
      ctx.fillStyle = "#b59ce9";
      bars.marks.forEach((cs, index) => {
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
    ctx.fillStyle = "#121c25";
    ctx.fillRect(0, 0, width, WAVE_HEIGHT);
    ctx.strokeStyle = "#263b48";
    ctx.beginPath();
    ctx.moveTo(0, WAVE_HEIGHT / 2);
    ctx.lineTo(width, WAVE_HEIGHT / 2);
    ctx.stroke();
    if (!state.audioBuffer) {
      ctx.fillStyle = "#657987";
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
      ctx.strokeStyle = channelIndex === 0 ? "#78bfd0" : "#5da8bd";
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
      ctx.strokeStyle = "#263b48";
      ctx.beginPath();
      ctx.moveTo(0, WAVE_HEIGHT / 2);
      ctx.lineTo(width, WAVE_HEIGHT / 2);
      ctx.stroke();
    }
    ctx.fillStyle = "rgba(53, 132, 160, .08)";
    ctx.fillRect(0, 0, width, WAVE_HEIGHT);
    ctx.fillStyle = "#8bbdca";
    ctx.font = "9px Segoe UI, sans-serif";
    ctx.fillText("AUDIO · " + formatTime(state.audioBuffer.duration) +
      " · " + state.audioBuffer.numberOfChannels + " CH", 10, 12);
  }

  function drawMarkers(width, pps) {
    const canvas = $("markersCanvas");
    const height = Math.max(MARKER_HEIGHT, state.lanes.length * MARKER_HEIGHT);
    const ctx = setCanvasSize(canvas, width, height);
    ctx.fillStyle = "#121a22";
    ctx.fillRect(0, 0, width, height);
    const colors = {
      native: "#8096a6",
      beats: "#54b88f",
      downbeats: "#b28be8",
      onsets: "#d99b56",
      sections: "#4fa9b7",
      phrases: "#8c79c7",
      energy: "#6ca4b7",
      stops: "#d56e70",
      "vocal-regions": "#5ea8d9",
      syllables: "#d48db9"
    };
    state.lanes.forEach((lane, laneIndex) => {
      const y = laneIndex * MARKER_HEIGHT;
      ctx.fillStyle = laneIndex % 2 ? "#141e27" : "#111a22";
      ctx.fillRect(0, y, width, MARKER_HEIGHT);
      ctx.strokeStyle = "#25323d";
      ctx.beginPath();
      ctx.moveTo(0, y + MARKER_HEIGHT - .5);
      ctx.lineTo(width, y + MARKER_HEIGHT - .5);
      ctx.stroke();
      const color = colors[lane.kind] || "#8096a6";
      if (lane.kind === "energy") {
        const maximum = Math.max(0.000001, ...lane.events.map((event) => Number(event.rms) || 0));
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
      for (const event of lane.events) {
        const time = event.time != null ? Number(event.time) : Number(event.start);
        if (!Number.isFinite(time) || time < 0) continue;
        const x = time * pps;
        if (lane.kind === "vocal-regions") {
          const end = Number(event.end);
          if (Number.isFinite(end) && end > time) {
            ctx.fillStyle = "rgba(74, 151, 199, .28)";
            ctx.fillRect(x, y + 5, Math.max(2, (end - time) * pps), 12);
            ctx.strokeStyle = color;
            ctx.strokeRect(x, y + 5, Math.max(2, (end - time) * pps), 12);
          }
        } else {
          ctx.strokeStyle = color;
          ctx.lineWidth = lane.kind === "downbeats" ? 2 : 1;
          ctx.beginPath();
          ctx.moveTo(Math.floor(x) + .5, y + (lane.kind === "onsets" ? 10 : 2));
          ctx.lineTo(Math.floor(x) + .5, y + MARKER_HEIGHT - 3);
          ctx.stroke();
        }
      }
    });
  }

  function effectColor(effect) {
    if (effect.type === "TWINKLE") return "#a17ce0";
    if (effect.type === "SHIMMER") return "#d79a4e";
    if (effect.type === "INTENSITY") return "#419fc7";
    return "#7f8b96";
  }

  function drawTracks(width, pps) {
    const canvas = $("tracksCanvas");
    const height = Math.max(ROW_HEIGHT, state.rows.length * ROW_HEIGHT);
    const ctx = setCanvasSize(canvas, width, height);
    ctx.fillStyle = "#10171f";
    ctx.fillRect(0, 0, width, height);

    for (let second = 0; second <= state.sequence.durationSeconds; second++) {
      const x = second * pps;
      ctx.strokeStyle = second % 5 === 0 ? "#293844" : "#1b2731";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(Math.floor(x) + .5, 0);
      ctx.lineTo(Math.floor(x) + .5, height);
      ctx.stroke();
    }
    const bars = state.sequence.timingGrids.find((grid) => /^bars?$/i.test(grid.name));
    if (bars) {
      ctx.strokeStyle = "rgba(176, 140, 230, .23)";
      bars.marks.forEach((cs) => {
        const x = (cs / 100) * pps;
        ctx.beginPath();
        ctx.moveTo(Math.floor(x) + .5, 0);
        ctx.lineTo(Math.floor(x) + .5, height);
        ctx.stroke();
      });
    }

    state.rows.forEach((row, index) => {
      const y = index * ROW_HEIGHT;
      if (row.kind === "group") {
        ctx.fillStyle = "#1b2732";
        ctx.fillRect(0, y, width, ROW_HEIGHT);
      } else if (row.kind === "prop") {
        ctx.fillStyle = "#18212a";
        ctx.fillRect(0, y, width, ROW_HEIGHT);
      } else {
        ctx.fillStyle = index % 2 ? "#111a22" : "#121c25";
        ctx.fillRect(0, y, width, ROW_HEIGHT);
        for (const effect of row.channel.effects) {
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
          if (state.selectedEffect === effect) {
            ctx.strokeStyle = "#f3f7fa";
            ctx.lineWidth = 1.5;
            ctx.strokeRect(x1, y + 3, blockWidth, ROW_HEIGHT - 6);
          }
        }
      }
      ctx.strokeStyle = "#202d38";
      ctx.beginPath();
      ctx.moveTo(0, y + ROW_HEIGHT - .5);
      ctx.lineTo(width, y + ROW_HEIGHT - .5);
      ctx.stroke();
    });
  }

  function updatePlayhead() {
    if (!state.sequence) return;
    const seconds = Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
    const visibleTime = Math.min(seconds, state.sequence.durationSeconds);
    playhead.style.left = (visibleTime * state.pxPerSecond) + "px";
    playhead.style.display = state.audioBuffer ? "block" : "none";
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
    const width = Math.max(canvasViewport.clientWidth, Math.ceil(state.sequence.durationSeconds * state.pxPerSecond));
    $("canvasContent").style.width = width + "px";
    $("labelsContent").style.height = (RULER_HEIGHT + WAVE_HEIGHT +
      state.lanes.length * MARKER_HEIGHT + state.rows.length * ROW_HEIGHT) + "px";
    drawRuler(width, state.sequence.durationSeconds, state.pxPerSecond);
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
    try {
      if (file.size > MAX_XML_BYTES) throw new Error("Sequence exceeds the 50 MiB input limit.");
      const doc = parseXmlDocument(await file.text());
      state.sequence = parseSequence(doc, file.name);
      state.collapsedGroups.clear();
      state.collapsedProps.clear();
      state.selectedEffect = null;
      $("welcome").classList.add("hidden");
      $("editor").classList.remove("hidden");
      $("inspectorContent").textContent = "Select an effect block to inspect its native settings and exact timing.";
      renderSequenceStats();
      refreshTimeline();
      setBanner("Loaded " + state.sequence.props.length + " native props, " +
        state.sequence.channelCount + " channels, and " + state.sequence.effectCount.toLocaleString() +
        " effects. Source sequence remains read-only.", "good");
      if (state.audioBuffer) compareDurations();
    } catch (error) {
      setBanner(error.message || String(error), "error");
    }
  }

  async function decodeWaveform(file) {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) throw new Error("This browser does not support Web Audio waveform decoding.");
    const context = new AudioContextClass();
    try {
      const audioBytes = await file.arrayBuffer();
      const prefix = new Uint8Array(audioBytes, 0, Math.min(4, audioBytes.byteLength));
      const hasId3 = prefix.length >= 3 && prefix[0] === 73 && prefix[1] === 68 && prefix[2] === 51;
      const hasMpegSync = prefix.length >= 2 && prefix[0] === 255 && (prefix[1] & 224) === 224;
      const mislabeledMp3 = file.name.toLowerCase().endsWith(".mp4") && (hasId3 || hasMpegSync);
      const playbackSource = mislabeledMp3
        ? new Blob([audioBytes], { type: "audio/mpeg" })
        : file;
      const buffer = await context.decodeAudioData(audioBytes.slice(0));
      if (buffer.duration < 2 || buffer.duration > 1800) {
        throw new Error("Audio duration must be between 2 seconds and 30 minutes.");
      }
      state.audioBuffer = buffer;
      state.waveformPeaks = buildWaveformPeaks(buffer);
      if (state.audioUrl) URL.revokeObjectURL(state.audioUrl);
      state.audioUrl = URL.createObjectURL(playbackSource);
      audio.src = state.audioUrl;
      $("playButton").disabled = false;
      $("stopButton").disabled = false;
      if (state.sequence) refreshTimeline();
      compareDurations();
      return buffer.duration;
    } finally {
      await context.close();
    }
  }

  function compareDurations() {
    if (!state.sequence || !state.audioBuffer) return;
    const delta = state.audioBuffer.duration - state.sequence.durationSeconds;
    if (Math.abs(delta) > 0.25) {
      setBanner("Audio and sequence durations differ by " + delta.toFixed(2) +
        " seconds. Check that the selected recording matches this sequence.", "warn");
    }
  }

  async function analyzeSelectedAudio(file) {
    if (!file) return;
    const meter = $("meterSelect").value;
    setBanner("Analyzing the selected audio locally: tempo, beats, downbeats, transients, sections, and pauses…");
    try {
      const response = await fetch("/api/analyze?beats_per_bar=" + meter, {
        method: "POST",
        headers: {
          "Content-Type": "application/octet-stream",
          "X-Audio-Filename": encodeURIComponent(file.name)
        },
        body: file
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Local analysis failed.");
      state.analysis = payload.report;
      renderSequenceStats();
      refreshTimeline();
      const analysis = state.analysis.analysis;
      $("analysisBanner").title = analysis.method + "\n" + analysis.provenance +
        "\nLimitations: " + analysis.limitations.join(" ");
      const bpm = analysis.tempo && analysis.tempo.bpm != null ? analysis.tempo.bpm + " BPM" : "tempo unavailable";
      const warning = payload.warning ? " " + payload.warning : "";
      setBanner("Audio analysis complete: " + bpm + "; " + analysis.beats.length +
        " beat candidates, " + analysis.downbeats.length + " downbeats, " +
        analysis.onsets.length + " transients, " + analysis.section_candidates.length +
        " section candidates. Estimates remain editable/reviewable." + warning, "good");
    } catch (error) {
      setBanner("Waveform loaded. Automatic analysis unavailable: " +
        (error.message || String(error)) + " Start the workspace with lor-sequence-ui to enable local analysis, or load a saved analysis JSON.", "warn");
    }
  }

  async function loadAudio(file) {
    if (!file) return;
    if (file.size <= 0 || file.size > MAX_AUDIO_BYTES) {
      setBanner("Audio must be non-empty and no larger than 200 MiB.", "error");
      return;
    }
    state.audioFile = file;
    state.audioBuffer = null;
    state.waveformPeaks = null;
    state.analysis = null;
    state.vocals = null;
    if (state.audioUrl) URL.revokeObjectURL(state.audioUrl);
    state.audioUrl = null;
    audio.pause();
    audio.removeAttribute("src");
    audio.load();
    $("playButton").disabled = true;
    $("stopButton").disabled = true;
    $("playButton").textContent = "▶";
    $("analysisBanner").title = "";
    if (state.sequence) {
      renderSequenceStats();
      refreshTimeline();
    }
    try {
      const duration = await decodeWaveform(file);
      setBanner("Waveform decoded from the selected audio (" + formatTime(duration) +
        "). Starting local musical analysis…", "good");
      await analyzeSelectedAudio(file);
    } catch (error) {
      state.audioFile = null;
      state.audioBuffer = null;
      state.waveformPeaks = null;
      setBanner("Could not decode the selected audio: " + (error.message || String(error)), "error");
    }
  }

  async function loadAnalysis(file) {
    if (!file) return;
    try {
      if (file.size > MAX_JSON_BYTES) throw new Error("Analysis JSON exceeds the 5 MiB input limit.");
      const data = JSON.parse(await file.text());
      if (!data || typeof data !== "object") throw new Error("Analysis JSON must contain an object.");
      const analysis = data.analysis;
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
      state.analysis = data;
      renderSequenceStats();
      refreshTimeline();
      $("analysisBanner").title = data.analysis.method + "\n" + data.analysis.provenance +
        "\nLimitations: " + data.analysis.limitations.join(" ");
      setBanner("Loaded saved analysis. Beat, downbeat, onset, section, and silence markers are labeled as estimates.", "good");
    } catch (error) {
      setBanner(error.message || String(error), "error");
    }
  }

  async function loadVocals(file) {
    if (!file) return;
    try {
      if (file.size > MAX_JSON_BYTES) throw new Error("Vocal JSON exceeds the 5 MiB input limit.");
      const data = JSON.parse(await file.text());
      if (!data || typeof data !== "object") throw new Error("Vocal JSON must contain an object.");
      const duration = Number(data.duration_seconds);
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
      setBanner(error.message || String(error), "error");
    }
  }

  function inspectEffect(effect, row) {
    state.selectedEffect = effect;
    const attrs = effect.attributes;
    const lines = [
      row.prop.name + " · Channel " + (row.channelIndex + 1),
      effect.type + " · " + formatCentiseconds(effect.start) +
        " → " + formatCentiseconds(effect.end),
      "Duration: " + ((effect.end - effect.start) / 100).toFixed(2) + " s",
      "Intensity: " + (attrs.intensity != null ? attrs.intensity :
        (attrs.startIntensity != null ? attrs.startIntensity + " → " + attrs.endIntensity : "not specified")),
      "Native attributes: " + Object.keys(attrs).map((key) => key + "=" + attrs[key]).join(" · ")
    ];
    const inspector = $("inspectorContent");
    inspector.replaceChildren();
    lines.forEach((line, index) => {
      const item = document.createElement("div");
      if (index < 2) item.className = "inspector-primary";
      item.textContent = line;
      inspector.appendChild(item);
    });
    drawTracks(Number($("tracksCanvas").width), state.pxPerSecond);
  }

  function seekFromPointer(event, canvas) {
    if (!state.sequence) return;
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const seconds = Math.max(0, Math.min(state.sequence.durationSeconds, x / state.pxPerSecond));
    seekAudio(seconds);
  }

  function handleTrackClick(event) {
    if (!state.sequence) return;
    const canvas = $("tracksCanvas");
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const rowIndex = Math.floor(y / ROW_HEIGHT);
    const row = state.rows[rowIndex];
    const seconds = Math.max(0, x / state.pxPerSecond);
    if (row && row.kind === "channel") {
      const cs = seconds * 100;
      const effect = row.channel.effects.find((item) => cs >= item.start && cs < item.end);
      if (effect) {
        inspectEffect(effect, row);
        return;
      }
    }
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
      state.pxPerSecond = Math.max(1, Math.min(48, Math.floor(available / state.sequence.durationSeconds)));
      $("zoomSlider").value = String(state.pxPerSecond);
      refreshTimeline();
      canvasViewport.scrollLeft = 0;
    });
    $("meterSelect").addEventListener("change", () => {
      if (state.audioFile) analyzeSelectedAudio(state.audioFile);
    });
    $("playButton").addEventListener("click", async () => {
      if (!state.audioFile) return;
      if (audio.paused) {
        try {
          await audio.play();
          $("playButton").textContent = "Ⅱ";
          cancelAnimationFrame(state.animationFrame);
          state.animationFrame = requestAnimationFrame(tickPlayback);
        } catch (error) {
          setBanner("Audio playback could not start: " + (error.message || String(error)), "warn");
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
    $("markersCanvas").addEventListener("click", (event) => seekFromPointer(event, $("markersCanvas")));
    $("tracksCanvas").addEventListener("click", handleTrackClick);
  }

  setup();
})();