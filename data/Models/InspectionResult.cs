using System;
using System.Collections.Generic;
using System.Text;

namespace VisiPickData.Models
{
    public class InspectionResult
    {
        public int Id { get; set; }
        public DateTime Timestamp { get; set; }
        public string ComponentType { get; set; } = "";
        public string Class { get; set; } = "";
        public string DefectCode { get; set; } = "";
        public string Result { get; set; } = "";
        public double Confidence { get; set; }
        public int CycleTimeMs { get; set; }
        public int GateUsed { get; set; }
    }
}
