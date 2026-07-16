/* G.O.A.L. Cascade — Tableau de bord (client JS vanilla) */

const API = {
  cascades: '/api/cascades',
  cascade: (id) => `/api/cascades/${id}`,
  fichiers: (id) => `/api/cascades/${id}/fichiers`,
  flux: (id) => `/api/cascades/${id}/evenements/flux`,
  prompts: (id) => `/api/cascades/${id}/prompts`,
  prompt: (id, role) => `/api/cascades/${id}/prompts/${role}`,
  recu: (id) => `/api/cascades/${id}/recu`,
};

let idCourant = null;
let sourceEvenements = null;

async function chargerCascades() {
  const liste = document.getElementById('liste-cascades');
  const champ = document.getElementById('champ-recherche');
  const statut = document.getElementById('filtre-statut');
  const params = new URLSearchParams();
  if (champ && champ.value.trim()) params.set('q', champ.value.trim());
  if (statut && statut.value) params.set('statut', statut.value);
  const qs = params.toString();
  const url = API.cascades + (qs ? `?${qs}` : '');
  try {
    const reponse = await fetch(url).then(r => r.json());
    const cascades = reponse.cascades || [];
    if (cascades.length === 0) {
      liste.innerHTML = '<li class="vide">Aucune cascade.</li>';
      return;
    }
    liste.innerHTML = cascades.map(c => `
      <li data-id="${c.id_cascade}">
        <div class="objet-cascade" title="${echapper(c.objectif)}">${echapper(c.objectif)}</div>
        <div class="meta-cascade">
          <span class="pastille-statut ${c.statut}">${c.statut}</span>
          <span>iter ${c.iteration_courante}/${c.nb_max_iterations}</span>
          <span>$${(c.cout_cumule || 0).toFixed(4)}</span>
        </div>
      </li>
    `).join('');
    liste.querySelectorAll('li[data-id]').forEach(li => {
      li.addEventListener('click', () => selectionnerCascade(li.dataset.id));
    });
  } catch (e) {
    liste.innerHTML = `<li class="vide">Erreur: ${echapper(String(e))}</li>`;
  }
}

// Branche les filtres (recherche + statut) pour recharger à chaque changement.
document.addEventListener('DOMContentLoaded', () => {
  const champ = document.getElementById('champ-recherche');
  const statut = document.getElementById('filtre-statut');
  if (champ) champ.addEventListener('input', () => chargerCascades());
  if (statut) statut.addEventListener('change', () => chargerCascades());
});

async function selectionnerCascade(id) {
  if (idCourant === id) return;
  idCourant = id;
  document.querySelectorAll('#liste-cascades li').forEach(li => {
    li.classList.toggle('active', li.dataset.id === id);
  });
  document.getElementById('etat-vide').hidden = true;
  document.getElementById('vue-cascade').hidden = false;

  await chargerDetail(id);
  await chargerPrompts(id);
  demarrerFluxEvenements(id);
}

async function chargerDetail(id) {
  try {
    const d = await fetch(API.cascade(id)).then(r => r.json());
    afficherDetail(d);
    afficherHistorique(d.historique || []);
    afficherSynthese(d.derniere_synthese);
    afficherVerdict(d.verdict_final);
    afficherFichiers(id);
    surlignerNoeudActif(d);
  } catch (e) {
    console.error('chargerDetail', e);
  }
}

// Ouvre un fichier dans VS Code via le schéma URI vscode://file/
// Nécessite que VS Code soit enregistré comme handler du schéma vscode://
// (par défaut sur Linux/Mac/Windows quand installé via le binaire officiel).
function ouvrirDansVSCode(chemin) {
  // Encode le chemin pour l'URI (caractères spéciaux)
  const cheminEncode = encodeURI(chemin);
  const url = `vscode://file${cheminEncode.startsWith('/') ? '' : '/'}${cheminEncode}`;
  // Sur Linux/WSL le handler s'attend à un chemin local ; sur WSL
  // un chemin /home/... est reconnu directement.
  window.open(url, '_blank');
}

function afficherDetail(d) {
  document.getElementById('objectif-cascade').textContent = d.objectif;
  document.getElementById('id-cascade').textContent = d.id_cascade;
  const elStatut = document.getElementById('statut-cascade');
  elStatut.textContent = d.statut;
  elStatut.className = `pastille ${d.statut}`;

  const elVerdict = document.getElementById('verdict-cascade');
  if (d.verdict_final) {
    elVerdict.textContent = d.verdict_final.decision;
    elVerdict.className = `pastille ${d.verdict_final.decision}`;
    elVerdict.title = d.verdict_final.justification;
  } else {
    elVerdict.textContent = '—';
    elVerdict.className = 'pastille';
  }
  document.getElementById('cout-cascade').textContent = `$${(d.cout_cumule || 0).toFixed(4)}`;
}

function afficherHistorique(historique) {
  const tbody = document.querySelector('#table-historique tbody');
  tbody.innerHTML = historique.map(h => `
    <tr>
      <td>${h.iteration}</td>
      <td>${h.role}</td>
      <td>${h.fournisseur}</td>
      <td>${h.modele}</td>
      <td class="numerique">${h.jetons_entree}</td>
      <td class="numerique">${h.jetons_sortie}</td>
      <td class="numerique">$${(h.cout_usd || 0).toFixed(4)}</td>
      <td class="numerique">${h.latence_ms}ms</td>
    </tr>
  `).join('');
}

function afficherSynthese(synthese) {
  const el = document.getElementById('synthese-json');
  el.textContent = synthese ? JSON.stringify(synthese, null, 2) : '(aucune synthèse)';
}

function afficherVerdict(verdict) {
  const el = document.getElementById('contenu-verdict');
  if (!verdict) {
    el.innerHTML = '<em>En attente…</em>';
    return;
  }
  el.innerHTML = `
    <div><strong>Décision :</strong> <span class="pastille ${verdict.decision}">${verdict.decision}</span></div>
    <div style="margin-top: 8px;"><strong>Justification :</strong> ${echapper(verdict.justification || '')}</div>
  `;
}

async function afficherFichiers(id) {
  try {
    const d = await fetch(API.fichiers(id)).then(r => r.json());
    const ul = document.getElementById('liste-fichiers');
    ul.innerHTML = (d.fichiers || []).map(f =>
      `<li>
        <span class="nom-fichier">${echapper(f.nom)}</span>
        <span class="taille-fichier">${formaterTaille(f.taille)}</span>
        <button class="vscode-btn" data-chemin="${echapper(f.chemin)}" title="Ouvrir dans VS Code">VS Code</button>
      </li>`
    ).join('');
    // Branche les boutons VS Code
    ul.querySelectorAll('.vscode-btn').forEach(btn => {
      btn.addEventListener('click', () => ouvrirDansVSCode(btn.dataset.chemin));
    });
  } catch (e) {
    document.getElementById('liste-fichiers').innerHTML = `<li>Erreur: ${echapper(String(e))}</li>`;
  }
}

function surlignerNoeudActif(d) {
  document.querySelectorAll('.noeud').forEach(n => {
    n.classList.remove('actif', 'termine');
  });
  const roleParIter = { 1: 'producteur', 2: 'critique', 3: 'adversaire', 4: 'arbitre' };
  for (let i = 1; i < d.iteration_courante; i++) {
    const noeud = document.querySelector(`.noeud[data-role="${roleParIter[i]}"]`);
    if (noeud) noeud.classList.add('termine');
  }
  if (d.statut === 'en_cours' && d.iteration_courante >= 1 && d.iteration_courante <= 4) {
    const noeudActif = document.querySelector(`.noeud[data-role="${roleParIter[d.iteration_courante]}"]`);
    if (noeudActif) noeudActif.classList.add('actif');
  }
  if (d.verdict_final || d.statut === 'arrete' || d.statut === 'arrete_force') {
    const noeudVerdict = document.querySelector('.noeud.verdict');
    if (noeudVerdict) noeudVerdict.classList.add('termine');
  }
}

async function chargerPrompts(id) {
  try {
    const prompts = await fetch(API.prompts(id)).then(r => r.json());
    document.querySelectorAll('.panneau-prompt').forEach(p => {
      const role = p.dataset.role;
      const ta = p.querySelector('.editeur-prompt');
      ta.value = prompts[role] || '';
    });
  } catch (e) {
    console.error('chargerPrompts', e);
  }
}

async function sauvegarderPrompt(role) {
  if (!idCourant) return;
  const panneau = document.querySelector(`.panneau-prompt[data-role="${role}"]`);
  const ta = panneau.querySelector('.editeur-prompt');
  const statut = panneau.querySelector('.statut-sauvegarde');
  try {
    const r = await fetch(API.prompt(idCourant, role), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ contenu: ta.value }),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();
    statut.textContent = `✓ Sauvegardé (${d.octets} octets)`;
    statut.classList.remove('erreur');
    setTimeout(() => statut.textContent = '', 3000);
  } catch (e) {
    statut.textContent = `✗ ${e.message}`;
    statut.classList.add('erreur');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.bouton-sauvegarder-prompt').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const role = e.target.closest('.panneau-prompt').dataset.role;
      sauvegarderPrompt(role);
    });
  });

  document.getElementById('bouton-rafraichir').addEventListener('click', () => {
    chargerCascades();
    if (idCourant) chargerDetail(idCourant);
  });
});

function demarrerFluxEvenements(id) {
  if (sourceEvenements) sourceEvenements.close();
  const elStatut = document.getElementById('etat-connexion');
  const elFlux = document.getElementById('flux-evenements');

  sourceEvenements = new EventSource(API.flux(id));
  sourceEvenements.onopen = () => {
    elStatut.textContent = '● connecté';
    elStatut.classList.remove('deconnecte');
    elStatut.classList.add('connecte');
  };
  sourceEvenements.onerror = () => {
    elStatut.textContent = '● déconnecté';
    elStatut.classList.add('deconnecte');
    elStatut.classList.remove('connecte');
  };
  sourceEvenements.addEventListener('journal', (ev) => {
    try {
      const evenement = JSON.parse(ev.data);
      const ligne = `[${evenement.sequence}] ${evenement.event} ${JSON.stringify(evenement).slice(0, 200)}`;
      elFlux.textContent = (elFlux.textContent + '\n' + ligne).split('\n').slice(-50).join('\n');
      elFlux.scrollTop = elFlux.scrollHeight;
      if (['appel_fournisseur_termine', 'course_terminee', 'derive_arret_force'].includes(evenement.event)) {
        chargerDetail(id);
      }
    } catch (e) {
      console.error('analyse SSE', e);
    }
  });
  sourceEvenements.addEventListener('snapshot', () => {
    chargerDetail(id);
  });
}

function echapper(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

function formaterTaille(n) {
  if (n < 1024) return `${n} o`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} Ko`;
  return `${(n / 1024 / 1024).toFixed(2)} Mo`;
}

chargerCascades();
setInterval(chargerCascades, 10000);
