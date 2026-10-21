<svg id="topology" viewBox="0 0 900 520" aria-label="FL topology">
  <defs>
    <linearGradient id="cloudGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#4facfe"/>
      <stop offset="100%" stop-color="#00f2fe"/>
    </linearGradient>
    <filter id="glow">
      <feGaussianBlur stdDeviation="4" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  <g id="flows"></g>
  <line class="link" x1="450" y1="200" x2="180" y2="420"/>
  <line class="link" x1="450" y1="200" x2="450" y2="420"/>
  <line class="link" x1="450" y1="200" x2="720" y2="420"/>
  <g id="cloudNode" transform="translate(450,160)">
    <ellipse class="cloud-shadow" cx="0" cy="55" rx="95" ry="18"/>
    <path class="cloud-body" d="M-70 20 Q-70 -25 -25 -35 Q0 -55 35 -35 Q75 -35 75 5 Q95 5 85 35 Q70 55 30 55 L-40 55 Q-85 55 -70 20 Z" filter="url(#glow)"/>
    <text class="node-title" y="-5" fill="#e8eef9">Flower Server</text>
    <text class="node-sub" id="cloudSubtitle" y="18" fill="#8ba3c7">Cloud - FedAvg</text>
    <g class="nn-icon" transform="translate(-28,-8)">
      <circle cx="10" cy="10" r="6"/><circle cx="40" cy="0" r="6"/><circle cx="40" cy="22" r="6"/>
      <line x1="16" y1="10" x2="34" y2="2"/><line x1="16" y1="12" x2="34" y2="20"/>
    </g>
  </g>
  <g id="client-alpha" class="client-node" transform="translate(180,420)">
    <rect class="board-card" x="-70" y="-45" width="140" height="90" rx="12"/>
    <text class="node-title" y="-18" fill="#e8eef9">board-alpha</text>
    <text class="node-sub machine-line" y="0" fill="#6ec8ff">-</text>
    <text class="node-sub client-status" y="18" fill="#8ba3c7">offline</text>
    <text class="node-sub samples" y="36" fill="#8ba3c7">-</text>
  </g>
  <g id="client-beta" class="client-node" transform="translate(450,420)">
    <rect class="board-card" x="-70" y="-45" width="140" height="90" rx="12"/>
    <text class="node-title" y="-18" fill="#e8eef9">board-beta</text>
    <text class="node-sub machine-line" y="0" fill="#6ec8ff">-</text>
    <text class="node-sub client-status" y="18" fill="#8ba3c7">offline</text>
    <text class="node-sub samples" y="36" fill="#8ba3c7">-</text>
  </g>
  <g id="client-gamma" class="client-node" transform="translate(720,420)">
    <rect class="board-card" x="-70" y="-45" width="140" height="90" rx="12"/>
    <text class="node-title" y="-18" fill="#e8eef9">board-gamma</text>
    <text class="node-sub machine-line" y="0" fill="#6ec8ff">-</text>
    <text class="node-sub client-status" y="18" fill="#8ba3c7">offline</text>
    <text class="node-sub samples" y="36" fill="#8ba3c7">-</text>
  </g>
</svg>
