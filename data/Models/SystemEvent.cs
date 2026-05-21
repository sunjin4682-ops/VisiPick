using System;
using System.Collections.Generic;
using System.Text;

namespace VisiPickData.Models
{
    public class SystemEvent
    {
        public int Id { get; set; }
        public DateTime Timestamp { get; set; }
        public string Source { get; set; } = "";     // Camera/Robot/Gate/AGV/System
        public string EventType { get; set; } = "";  // INFO/WARNING/ERROR
        public string Message { get; set; } = "";
    }
}
