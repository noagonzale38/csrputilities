const tabs = Array.from(document.querySelectorAll(".wizard-tab"));
const panels = Array.from(document.querySelectorAll(".wizard-panel"));
const prevButton = document.getElementById("wizardPrev");
const nextButton = document.getElementById("wizardNext");

if (tabs.length && panels.length && prevButton && nextButton) {
  let step = 0;

  const paint = () => {
    tabs.forEach((tab, index) => tab.classList.toggle("active", index === step));
    panels.forEach((panel, index) => panel.classList.toggle("active", index === step));
    prevButton.disabled = step === 0;
    nextButton.disabled = step === panels.length - 1;
  };

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => {
      step = index;
      paint();
    });
  });

  prevButton.addEventListener("click", () => {
    step = Math.max(0, step - 1);
    paint();
  });

  nextButton.addEventListener("click", () => {
    step = Math.min(panels.length - 1, step + 1);
    paint();
  });

  paint();
}
