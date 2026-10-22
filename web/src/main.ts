import App from "./App.svelte";
import "./app.css";

const target = document.getElementById("app");
if (!target) throw new Error("точка монтирования не найдена");

export default new App({ target });
