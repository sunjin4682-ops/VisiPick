using System;
using System.Collections.Generic;
using System.Text;

namespace VisiPickData.Models
{
    public class AgvMission
    {
        public int Id { get; set; }
        public int AgvId { get; set; }
        public DateTime StartTime { get; set; }
        public DateTime? EndTime { get; set; }       // nullable
        public string Source { get; set; } = "";
        public string Destination { get; set; } = "";
        public string TrayClass { get; set; } = "";
        public int ItemCount { get; set; }
        public string Status { get; set; } = "대기";
    }
}
