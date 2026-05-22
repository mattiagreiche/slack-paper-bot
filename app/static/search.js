const form = document.querySelector("[data-live-search]");
const resultsList = document.querySelector("#results-list");
const resultCount = document.querySelector("#result-count");

if (form && resultsList && resultCount) {
  let timer;
  let controller;

  const buildQuery = () => {
    const data = new FormData(form);
    const params = new URLSearchParams();

    for (const [key, value] of data.entries()) {
      if (value !== "") {
        params.set(key, value);
      }
    }

    return params;
  };

  const runSearch = async () => {
    window.clearTimeout(timer);
    controller?.abort();
    controller = new AbortController();

    const params = buildQuery();
    const query = params.toString();
    const displayUrl = query ? `${form.action}?${query}` : form.action;
    const fetchUrl = query ? `/search/results?${query}` : "/search/results";

    form.classList.add("is-searching");

    try {
      const response = await fetch(fetchUrl, {
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });

      if (response.status === 401) {
        window.location.href = "/login";
        return;
      }

      if (!response.ok) {
        throw new Error(`Search failed with ${response.status}`);
      }

      const payload = await response.json();
      resultsList.innerHTML = payload.html;
      resultCount.textContent = payload.count;
      window.history.replaceState({}, "", displayUrl);
    } catch (error) {
      if (error.name !== "AbortError") {
        console.error(error);
      }
    } finally {
      form.classList.remove("is-searching");
    }
  };

  const queueSearch = () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(runSearch, 350);
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    runSearch();
  });

  form.querySelectorAll("input, select").forEach((element) => {
    const eventName = element.tagName === "SELECT" ? "change" : "input";
    element.addEventListener(eventName, queueSearch);
  });
}
