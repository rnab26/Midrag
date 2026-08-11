document.addEventListener("DOMContentLoaded", () => {
  const mappingsDiv = document.getElementById("mappings");
  const template = document.getElementById("mapping-row-template");
  const addBtn = document.getElementById("add-mapping");
  const form = document.getElementById("job-form");
  const statusEl = document.getElementById("job-status");

  if (!form) return;

  function addMappingRow() {
    const node = template.content.cloneNode(true);
    const row = node.querySelector(".mapping-row");
    const indexInput = node.querySelector(".mapping-index");
    indexInput.value = mappingsDiv.children.length;
    node.querySelector(".remove-mapping").addEventListener("click", () => row.remove());
    mappingsDiv.appendChild(node);
  }

  addBtn.addEventListener("click", addMappingRow);
  addMappingRow(); // start with one row

  async function pollJob(jobId) {
    for (let i = 0; i < 120; i++) {
      const res = await fetch(`/jobs/${jobId}`);
      const job = await res.json();
      if (job.status === "completed") {
        statusEl.innerHTML = `Terminé ! <a href="${job.result_url}" download>Télécharger le résultat</a>`;
        return;
      }
      if (job.status === "failed") {
        statusEl.textContent = `Échec : ${job.error}`;
        return;
      }
      statusEl.textContent = `Statut : ${job.status}…`;
      await new Promise((r) => setTimeout(r, 2000));
    }
    statusEl.textContent = "Toujours en cours, regarde l'historique plus tard.";
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const targetId = document.getElementById("target-select").value;
    const mappings = [...mappingsDiv.querySelectorAll(".mapping-row")].map((row) => ({
      source_face_asset_id: row.querySelector(".mapping-source").value,
      target_face_index: parseInt(row.querySelector(".mapping-index").value, 10),
    }));
    const faceEnhancer = document.getElementById("face-enhancer").checked;
    const lipSync = document.getElementById("lip-sync").checked;

    statusEl.textContent = "Envoi…";
    const res = await fetch("/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        target_asset_id: targetId,
        mappings,
        face_enhancer: faceEnhancer,
        lip_sync: lipSync,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      statusEl.textContent = `Erreur : ${err.detail || res.statusText}`;
      return;
    }
    const job = await res.json();
    statusEl.textContent = `Job lancé (statut : ${job.status})…`;
    pollJob(job.id);
  });
});
