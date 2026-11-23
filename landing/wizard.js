(() => {
  const wizard = document.getElementById("wizard-button");
  const bubble = document.getElementById("wizard-bubble");
  let timeout;

  wizard.addEventListener("click", () => {
    clearTimeout(timeout);
    bubble.hidden = false;
    bubble.textContent = "I CAST REGULAR MISSILE";
    timeout = setTimeout(() => {
      bubble.hidden = true;
      bubble.textContent = "";
    }, 4000);
  });
})();
