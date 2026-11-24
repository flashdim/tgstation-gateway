(() => {
  for (const button of document.querySelectorAll(".character-button")) {
    const bubble = button.nextElementSibling;
    let timeout;

    button.addEventListener("click", () => {
      clearTimeout(timeout);
      bubble.hidden = false;
      bubble.textContent = button.dataset.message;
      timeout = setTimeout(() => {
        bubble.hidden = true;
        bubble.textContent = "";
      }, 4000);
    });
  }
})();
