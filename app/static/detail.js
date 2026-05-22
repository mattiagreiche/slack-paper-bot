const modal = document.querySelector("[data-bibtex-modal]");
const openButton = document.querySelector("[data-open-bibtex]");
const closeButton = document.querySelector("[data-close-bibtex]");

if (modal && openButton && closeButton) {
  const textarea = modal.querySelector("textarea");

  const openModal = () => {
    modal.hidden = false;
    textarea?.focus();
    textarea?.select();
  };

  const closeModal = () => {
    modal.hidden = true;
    openButton.focus();
  };

  openButton.addEventListener("click", openModal);
  closeButton.addEventListener("click", closeModal);
  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      closeModal();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) {
      closeModal();
    }
  });
}
