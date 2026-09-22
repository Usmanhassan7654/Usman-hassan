const agents = [
  {
    id: "haramain", icon: "HG", type: "Sales agent", name: "Haramain Gift Concierge", company: "Haramain Gifts · Makkah & Madinah",
    capabilities: ["Catalogue grounding", "Budget allocation", "Multi-item orders", "Human handoff"],
    prompts: ["I have a $1,500 budget in Makkah", "10 Khatm-e-Quran in Makkah", "Can I order something not in the catalogue?"],
    welcome: "Assalamu Alaikum. I can build a gifting plan using the approved Haramain catalogue. Tell me your budget, city and preferred gifts.",
    evidence: ["Occasion Gifting / Khatm-e-Quran · $100", "Water Refill · $250", "Water Bottles · $125", "Energizer Bags · $75", "Faith Pack · $75", "Tasbih · $75"],
    respond(q) {
      const s=q.toLowerCase();
      if (/not in|outside|custom item|iphone|laptop/.test(s)) return refusal("That item is not present in the approved catalogue. I won’t invent availability or a price. I can offer a catalogue option or send the request for human review.", ["Catalogue boundary rule"]);
      if (/10|khatm|quran/.test(s)) return ok("10 Khatm-e-Quran gifts in Makkah total $1,000 (10 × $100). I can prepare this as the main order. Final availability and payment are confirmed by the team before placement.", ["Occasion Gifting / Khatm-e-Quran · $100 each", "Calculated total · $1,000"]);
      if (/1500|1,500/.test(s)) return ok("A catalogue-grounded $1,500 plan:\n• 10 Khatm-e-Quran gifts — $1,000\n• Water Refill — $250\n• Water Bottles — $125\n• Faith Pack — $75\n• Tasbih — $50 reserved; the listed Tasbih package is $75, so I will not exceed your budget.\n\nConfirmed subtotal: $1,450. Remaining: $50. You may keep the balance or revise an item.", ["Budget cap · $1,500", "Verified subtotal · $1,450", "No above-budget recommendation"]);
      if (/water|faith|tasbih|gift|budget|makkah|madina/.test(s)) return ok("I found matching catalogue options. Water Refill is $250, Water Bottles $125, Faith Pack $75 and Tasbih $75. Tell me the budget and city, and I’ll create a combination without exceeding it.", ["Approved Haramain catalogue", "Location required before order"]);
      return clarify("I can help with listed gifts, budget allocation, Makkah/Madinah selection, or an existing draft order. Please include at least one of those details.", ["Required fields · item, budget or location"]);
    }
  },
  {
    id: "hb", icon: "HB", type: "Sales agent", name: "AI Solution Advisor", company: "HB Innovations · Prototype service catalogue",
    capabilities: ["Needs discovery", "Solution matching", "Estimate bands", "Meeting qualification"],
    prompts: ["I need an AI sales agent for my website", "Can you automate CCTV monitoring?", "Promise delivery in one week"],
    welcome: "Tell me the business problem, users, data source and target timeline. I will match it to an approved HB Innovations prototype service—not invent a capability.",
    evidence: ["RAG Assistant · demo estimate from $1,800", "AI Sales Agent · from $2,500", "Voice Agent · from $2,800", "Computer Vision PoC · from $3,000"],
    respond(q) {
      const s=q.toLowerCase();
      if (/one week|guarantee|promise/.test(s)) return refusal("I cannot promise delivery before technical discovery. The approved workflow requires scope, integrations, data readiness and acceptance criteria before a timeline is committed.", ["Delivery policy · discovery before commitment"]);
      if (/sales|website|chat/.test(s)) return ok("Best match: AI Sales Agent prototype (demo estimate from $2,500). It can qualify visitors, recommend approved services and prepare a handoff. To produce a real proposal I still need: website URL, catalogue/pricing source, lead destination and required languages.", ["Service match · AI Sales Agent", "Demo estimate · from $2,500", "4 discovery fields outstanding"]);
      if (/cctv|camera|ppe|vision|video/.test(s)) return ok("Best match: Computer Vision Proof of Concept (demo estimate from $3,000). The next step is a sample video and one measurable event—for example PPE violation, entry count or phone-use duration. Accuracy cannot be promised before validation on your footage.", ["Service match · Computer Vision PoC", "Validation rule · client footage required"]);
      if (/voice|call/.test(s)) return ok("Best match: Voice Agent prototype (demo estimate from $2,800). I need the call type, languages, knowledge source, escalation number and expected concurrent calls before a real quote.", ["Service match · Voice Agent", "Concurrency affects deployment"]);
      return clarify("I can match sales agents, voice agents, RAG assistants and computer-vision PoCs. What process is costing your team the most time today?", ["Approved prototype service list"]);
    }
  },
  {
    id: "midrar", icon: "MI", type: "Sales agent", name: "Enrollment & Course Advisor", company: "Al Midrar Institute · Enrollment prototype",
    capabilities: ["Course guidance", "Interest qualification", "Multilingual context", "Validated callback"],
    prompts: ["Mujhe Tajweed-ul-Quran course chahiye", "Book my admission now", "Tell me an unavailable course fee"],
    welcome: "Assalamu Alaikum. I can guide visitors through approved Al Midrar course and support information, understand genuine interest, and prepare a callback. I do not confirm enrollment or fees without a verified record.",
    evidence: ["Supported topics · courses and Tajweed-ul-Quran", "Support areas · counselling, welfare, Umrah and LMS", "Languages · English, Urdu, Roman Urdu", "Enrollment action · validated human callback"],
    respond(q) {
      const s=q.toLowerCase();
      if (/fee|price|cost|pkr|rs/.test(s)) return refusal("No verified fee is loaded for that request, so I will not invent an amount. I can record the course name, your city and contact preference for an institute callback.", ["Fee record · unavailable", "Human confirmation required"]);
      if (/tajweed|quran|قرآن|course/.test(s)) return ok("Tajweed-ul-Quran is within the approved course-guidance scope. Aap apna current level, preferred language aur available timing share karein. Main suitable enquiry summary bana kar counsellor callback ke liye tayyar karunga.", ["Topic match · Tajweed-ul-Quran", "Required fields · level, language, timing"]);
      if (/book|admission|enrol|enroll|register/.test(s)) return refusal("I can prepare an enrollment request, but I cannot claim admission is confirmed without the institute system or a counsellor. Please provide your name, course, phone number and preferred callback time.", ["Action boundary · callback request only", "Admission confirmation · human/system required"]);
      if (/umrah|welfare|counsel|lms/.test(s)) return ok("This topic is covered by the institute support scope. Tell me the specific question and your preferred language; I will answer from the approved information or route it to the relevant team.", ["Approved support scope · counselling, welfare, Umrah, LMS"]);
      return clarify("Aap course guidance, Tajweed-ul-Quran, counselling, welfare, Umrah ya LMS ke baray mein pooch saktay hain. For follow-up, I will need a course/topic and preferred contact time.", ["Supported multilingual guidance"]);
    }
  },
  {
    id: "call", icon: "GS", type: "Call handling agent", name: "Insurance Call Desk", company: "GulfShield Insurance · Fictional voice-flow prototype",
    capabilities: ["Speech input", "Intent routing", "Incident checklist", "Emergency escalation"],
    prompts: ["I had an accident and need to report it", "Tell me my claim status", "Someone is injured"],
    welcome: "Thank you for calling GulfShield, a fictional demo insurer. I can guide an incident report, explain the approved process or route urgent cases. I will never claim a backend action succeeded unless it is verified.",
    evidence: ["Safety first · move only if safe", "Incident fields · policy ID, location, time, parties, injuries", "Claim status requires authenticated backend", "Emergency services override normal flow"],
    respond(q) {
      const s=q.toLowerCase();
      if (/injur|ambulance|fire|danger|emergency/.test(s)) return ok("Your safety comes first. Please contact local emergency services now and move to a safe place only if you can do so safely. I am marking this demo flow for urgent human escalation; I am not claiming an emergency call has been placed.", ["Emergency escalation policy", "No unverified action claim"]);
      if (/accident|incident|crash|report/.test(s)) return ok("I can start the incident checklist. Please provide: 1) policy ID, 2) exact location, 3) date and time, 4) whether anyone is injured, and 5) other vehicles or property involved. Do not share payment-card details.", ["Approved incident checklist · 5 required fields"]);
      if (/claim|status/.test(s)) return refusal("I cannot see a live claim backend in this prototype, so I will not invent a status. An authenticated claims-system lookup or human representative is required.", ["Backend status · not connected", "Escalation required"]);
      return clarify("Is this a new accident report, an emergency, a policy question or an existing claim? I’ll route the call using the approved flow.", ["Supported call intents · 4"]);
    }
  },
  leadAgent("hb-leads", "AI", "AI Services Lead Engine", "HB Innovations · Synthetic B2B prospect sandbox", "AI automation", [
    ["PalmMart Retail", "High", 91, "14 stores; manual customer-support queue", "AI support + sales assistant"],
    ["Vertex Logistics", "High", 87, "Fleet video and manual incident reviews", "Computer vision monitoring"],
    ["Crescent Clinics", "Medium", 74, "Repeated appointment and FAQ calls", "Multilingual voice agent"]
  ]),
  leadAgent("solar-leads", "SL", "Solar Commercial Lead Engine", "SunPeak Energy · Fictional Multan prototype", "commercial solar", [
    ["Multan Textile Works", "High", 93, "Daytime industrial load; large roof footprint", "Energy audit + solar feasibility"],
    ["Al Noor Hospital", "High", 88, "24/7 critical load and generator dependence", "Hybrid solar assessment"],
    ["South Punjab Cold Store", "Medium", 79, "High cooling load; seasonal peaks", "Load-profile consultation"]
  ]),
  leadAgent("dairy-leads", "DB", "Dairy B2B Lead Engine", "Marhaba Dairy · Synthetic buyer sandbox", "fresh milk supply", [
    ["Royal Bakers Multan", "High", 90, "Daily dairy use across three branches", "Recurring wholesale milk supply"],
    ["Chenab View Hotel", "High", 85, "Breakfast and banquet demand", "Scheduled bulk delivery"],
    ["City School Canteens", "Medium", 72, "Multiple consumption points", "Pilot supply contract"]
  ])
];

function leadAgent(id, icon, name, company, niche, leads) {
  return {
    id, icon, type: "Lead generation agent", name, company,
    capabilities: ["ICP filtering", "Rule-based scoring", "Evidence trail", "Personalised draft"],
    prompts: ["Run the lead pipeline", "Why is the top lead qualified?", "Write outreach for the top lead"],
    welcome: `This ${niche} prototype scores a labelled synthetic dataset. It demonstrates qualification and outreach logic without pretending the example companies were live-verified.`,
    evidence: leads.map(x => `${x[0]} · score ${x[2]} · ${x[3]}`),
    respond(q) {
      const s=q.toLowerCase(), top=leads[0];
      if (/outreach|email|message|pitch/.test(s)) return ok(`Draft for ${top[0]}:\n\nHi ${top[0]} team, I noticed your likely need around ${top[3].toLowerCase()}. We help businesses evaluate ${top[4].toLowerCase()} with a focused pilot tied to one measurable outcome. Would a 20-minute discovery call next week be useful?\n\nThis is a draft only. A human must verify the company and contact before sending.`, [`Lead · ${top[0]}`, `Observed signal · ${top[3]}`, "Send status · approval required"]);
      if (/why|qualif|top|score/.test(s)) return ok(`${top[0]} ranks first at ${top[2]}/100. The score combines problem fit (40%), likely value (30%), timing signal (20%) and data confidence (10%). Its recorded signal is: ${top[3]}.`, [`Scoring output · ${top[2]}/100`, "Deterministic weighted rubric"]);
      if (/run|pipeline|lead|find|list/.test(s)) return ok("Pipeline result:\n" + leads.map((x,i)=>`${i+1}. ${x[0]} — ${x[1]} fit (${x[2]}/100)\n   Signal: ${x[3]}\n   Offer: ${x[4]}`).join("\n\n") + "\n\nAll records are synthetic demo data and require live verification before outreach.", leads.map(x=>`${x[0]} · ${x[2]}/100`));
      return clarify("Ask me to run the pipeline, explain a score or draft outreach. Live contact discovery is intentionally not represented as active in this static prototype.", ["Dataset · synthetic", "Live verification · required"]);
    }
  };
}

function ok(text,evidence){ return {text,evidence,status:"Grounded answer"}; }
function refusal(text,evidence){ return {text,evidence,status:"Safe refusal"}; }
function clarify(text,evidence){ return {text,evidence,status:"Needs clarification"}; }

const list=document.querySelector("#agent-list"), conversation=document.querySelector("#conversation"), evidence=document.querySelector("#evidence-content"), form=document.querySelector("#chat-form"), input=document.querySelector("#message");
let active=agents[0];

agents.forEach((a,i)=>{
  const b=document.createElement("button"); b.className="agent-button"; b.type="button"; b.dataset.id=a.id;
  b.innerHTML=`<span class="icon">${a.icon}</span><span><strong>${a.name}</strong><small>${a.type}</small></span><span class="arrow">↗</span>`;
  b.addEventListener("click",()=>selectAgent(a,i)); list.appendChild(b);
});

function selectAgent(a,index){
  active=a; document.querySelectorAll(".agent-button").forEach(x=>x.classList.toggle("active",x.dataset.id===a.id));
  document.querySelector("#agent-index").textContent=String(index+1).padStart(2,"0"); document.querySelector("#agent-type").textContent=a.type.toUpperCase();
  document.querySelector("#agent-name").textContent=a.name; document.querySelector("#agent-company").textContent=a.company;
  document.querySelector("#capabilities").innerHTML=a.capabilities.map(x=>`<span>${x}</span>`).join("");
  conversation.innerHTML=""; addMessage(a.welcome,"agent"); setEvidence(a.evidence,"Approved knowledge loaded");
  const quick=document.querySelector("#quick-prompts"); quick.innerHTML=""; a.prompts.forEach(p=>{ const b=document.createElement("button"); b.type="button"; b.textContent=p; b.onclick=()=>run(p); quick.appendChild(b); });
  input.placeholder=a.type.includes("Lead")?"Ask the agent to qualify or draft…":"Ask a realistic customer question…";
}

function addMessage(text,kind,label){ const d=document.createElement("div"); d.className=`message ${kind}`; d.innerHTML=`<span class="message-label">${label || (kind==="user"?"YOU":"AGENT")}</span>${escapeHtml(text)}`; conversation.appendChild(d); conversation.scrollTop=conversation.scrollHeight; }
function setEvidence(items,label){ evidence.innerHTML=`<strong>${label}</strong><br>${items.map(x=>`<span class="evidence-tag">${escapeHtml(x)}</span>`).join("")}`; }
function run(q){ if(!q.trim()) return; addMessage(q,"user"); input.value=""; const result=active.respond(q); setTimeout(()=>{ addMessage(result.text,"agent",result.status.toUpperCase()); setEvidence(result.evidence,result.status); },220); }
function escapeHtml(v){ const d=document.createElement("div"); d.textContent=v; return d.innerHTML; }
form.addEventListener("submit",e=>{e.preventDefault();run(input.value);});
document.querySelector("#toggle-evidence").addEventListener("click",e=>{ const c=evidence.classList.toggle("collapsed"); e.currentTarget.textContent=c?"Show":"Hide"; });
selectAgent(agents[0],0);
