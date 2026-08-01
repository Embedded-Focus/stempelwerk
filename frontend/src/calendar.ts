import { Calendar } from "@fullcalendar/core";
import interactionPlugin from "@fullcalendar/interaction";
import timeGridPlugin from "@fullcalendar/timegrid";

import { getStatus } from "./api";
import "./styles.css";

const calendarElement = document.querySelector<HTMLElement>("#calendar");

if (!calendarElement) {
  throw new Error("Calendar root not found");
}

const calendar = new Calendar(calendarElement, {
  plugins: [interactionPlugin, timeGridPlugin],
  initialView: "timeGridWeek",
  firstDay: 1,
  nowIndicator: true,
  selectable: true,
  editable: true,
  allDaySlot: false,
  slotDuration: "00:15:00",
  businessHours: {
    daysOfWeek: [1, 2, 3, 4, 5],
    startTime: "07:00",
    endTime: "20:00"
  },
  headerToolbar: {
    left: "prev,next today",
    center: "title",
    right: "timeGridDay,timeGridWeek"
  }
});

calendar.render();

void getStatus().catch((error: unknown) => {
  console.error(error);
});

